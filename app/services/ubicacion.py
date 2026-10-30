"""Clasificación geográfica de un evento para la ficha de los listados.

Devuelve una frase corta con el ámbito (Chile continental/insular/costa, mar
chileno, país del continente, costa afuera o alta mar) y, cuando corresponde,
la distancia a la costa o a la frontera. Usa los polígonos de Chile y sus
vecinos que ya carga ``borders.py`` desde el core, y agrega tierra 10m y países
50m de Natural Earth para los eventos fuera del cono sur.
"""

from __future__ import annotations

from functools import lru_cache

from . import borders

RADIO_COSTA_KM = 200.0
TOLERANCIA_COSTA_KM = 2.0
AREA_MIN_ISLA = 0.001

_GEOD = None
_CACHE_DATOS = None
_CACHE_ERROR = False


def limpiar_cache() -> None:
    """Olvida geometrías y clasificaciones (pruebas)."""
    global _GEOD, _CACHE_DATOS, _CACHE_ERROR
    _GEOD = None
    _CACHE_DATOS = None
    _CACHE_ERROR = False
    _clasificar_cache.cache_clear()


def _geod():
    global _GEOD
    if _GEOD is None:
        from pyproj import Geod

        _GEOD = Geod(ellps="WGS84")
    return _GEOD


def _partir_chile(geometria):
    """(continental, insular) separando la parte de mayor área."""
    from shapely.ops import unary_union

    partes = list(getattr(geometria, "geoms", [geometria]))
    if not partes:
        return geometria, None
    mayor = max(partes, key=lambda g: g.area)
    islas = [g for g in partes if g is not mayor and g.area >= AREA_MIN_ISLA]
    return mayor, (unary_union(islas) if islas else None)


def _cargar_tierra():
    import shapefile
    from cartopy.io import shapereader
    from shapely.geometry import shape

    ruta = shapereader.natural_earth(
        resolution="10m", category="physical", name="land"
    )
    lector = shapefile.Reader(ruta)
    geoms = []
    for registro in lector.iterShapeRecords():
        if registro.shape.shapeType == 0 or not registro.shape.points:
            continue
        geom = shape(registro.shape.__geo_interface__)
        if not geom.is_empty:
            geoms.append(geom)
    if not geoms:
        raise ValueError("Natural Earth no trajo tierra")
    return geoms


def _cargar_otros_paises():
    import shapefile
    from cartopy.io import shapereader
    from shapely.geometry import shape
    from shapely.prepared import prep

    ruta = shapereader.natural_earth(
        resolution="50m", category="cultural", name="admin_0_countries"
    )
    lector = shapefile.Reader(ruta)
    campos = [f[0] for f in lector.fields[1:]]
    otros = []
    for registro in lector.iterShapeRecords():
        if registro.shape.shapeType == 0 or not registro.shape.points:
            continue
        datos = dict(zip(campos, registro.record))
        codigo = datos.get("ADM0_A3")
        if codigo in ("CHL", "PER", "BOL", "ARG"):
            continue
        nombre = (
            datos.get("NAME_ES")
            or datos.get("NAME")
            or datos.get("ADMIN")
            or codigo
            or ""
        )
        if not nombre:
            continue
        geom = shape(registro.shape.__geo_interface__)
        if geom.is_empty:
            continue
        otros.append((codigo, nombre, geom, prep(geom)))
    return otros


def _cargar_datos():
    """Carga (una vez) las capas; None si no se pudo."""
    global _CACHE_DATOS, _CACHE_ERROR
    if _CACHE_DATOS is not None:
        return _CACHE_DATOS
    if _CACHE_ERROR:
        return None
    try:
        from shapely.prepared import prep

        modulo = borders._modulo()
        datos_core = modulo._cargar_datos()
        if datos_core is None:
            raise ValueError("el core no trajo fronteras")
        _fronteras, paises, _prep = datos_core
        continental, insular = _partir_chile(paises["CHL"])
        _CACHE_DATOS = {
            "modulo": modulo,
            "chile": paises["CHL"],
            "continental": continental,
            "insular": insular,
            "prep_chile": prep(paises["CHL"]),
            "prep_continental": prep(continental),
            "prep_insular": prep(insular) if insular is not None else None,
            "vecinos": [(codigo, paises[codigo]) for codigo in ("PER", "BOL", "ARG")],
            "prep_vecinos": [
                (codigo, prep(paises[codigo])) for codigo in ("PER", "BOL", "ARG")
            ],
            "otros": _cargar_otros_paises(),
            "tierra": _cargar_tierra(),
        }
    except Exception:
        _CACHE_ERROR = True
        _CACHE_DATOS = None
    return _CACHE_DATOS


def _distancia_km(lat, lon, geometria):
    from shapely.geometry import Point
    from shapely.ops import nearest_points

    cercano = nearest_points(Point(lon, lat), geometria)[1]
    _, _, metros = _geod().inv(lon, lat, cercano.x, cercano.y)
    return metros / 1000.0


def _km_frontera(lat, lon):
    try:
        resultado = borders.frontera(lat, lon)
    except Exception:
        return None
    return resultado[1] if resultado else None


def _pais_en_punto(lon, lat, datos):
    from shapely.geometry import Point

    punto = Point(lon, lat)
    if datos["prep_chile"].contains(punto):
        return "Chile"
    nombres = getattr(datos["modulo"], "PAISES", {})
    for codigo, prep_vecino in datos["prep_vecinos"]:
        if prep_vecino.contains(punto):
            return nombres.get(codigo, codigo)
    for _codigo, nombre, _geom, prep_pais in datos["otros"]:
        if prep_pais.contains(punto):
            return nombre
    return None


def _km_texto(km):
    if km is None:
        return ""
    if km < 10:
        return f"{km:.1f} km"
    return f"{km:.0f} km"


def _clasificar_en_datos(lat, lon, datos):
    """Cálculo puro sobre capas ya cargadas (se prueba sin Natural Earth)."""
    from shapely.geometry import Point

    punto = Point(lon, lat)
    pais = _pais_en_punto(lon, lat, datos)
    if pais == "Chile":
        if datos["prep_insular"] is not None and datos["prep_insular"].contains(punto):
            return {
                "ambito": "chile_insular",
                "zona": "insular",
                "texto": "Chile · insular",
                "detalle": "",
                "pais": "Chile",
            }
        if datos["prep_continental"].contains(punto):
            return {
                "ambito": "chile_continental",
                "zona": "continental",
                "texto": "Chile · continental",
                "detalle": "",
                "pais": "Chile",
            }
        return {
            "ambito": "chile_insular",
            "zona": "insular",
            "texto": "Chile · insular",
            "detalle": "",
            "pais": "Chile",
        }

    if pais:
        km = _km_frontera(lat, lon)
        detalle = f"frontera {_km_texto(km)}" if km is not None else ""
        return {
            "ambito": "pais",
            "zona": "continente",
            "texto": pais,
            "detalle": detalle,
            "pais": pais,
        }

    km_chile = _distancia_km(lat, lon, datos["chile"])
    if km_chile <= TOLERANCIA_COSTA_KM:
        return {
            "ambito": "chile_costa",
            "zona": "costa",
            "texto": "Chile · costa",
            "detalle": f"{_km_texto(km_chile)} del borde",
            "pais": "Chile",
        }
    if km_chile <= datos["modulo"].RADIO_MAR_CHILENO_KM and _chile_cerca(
        lat, lon, km_chile, datos
    ):
        return {
            "ambito": "mar_chileno",
            "zona": "mar",
            "texto": "Mar chileno",
            "detalle": f"costa afuera · {_km_texto(km_chile)}",
            "pais": "Chile",
        }

    km_tierra = min(_distancia_km(lat, lon, geom) for geom in datos["tierra"])
    if km_tierra <= RADIO_COSTA_KM:
        return {
            "ambito": "costa_afuera",
            "zona": "costa",
            "texto": "Costa afuera",
            "detalle": f"{_km_texto(km_tierra)} de la costa",
            "pais": "",
        }
    return {
        "ambito": "alta_mar",
        "zona": "alta_mar",
        "texto": "Alta mar",
        "detalle": f"{_km_texto(km_tierra)} de la costa",
        "pais": "",
    }


def _chile_cerca(lat, lon, km_chile, datos):
    for _codigo, geometria in datos["vecinos"]:
        if _distancia_km(lat, lon, geometria) < km_chile:
            return False
    return True


@lru_cache(maxsize=8192)
def _clasificar_cache(lat, lon):
    datos = _cargar_datos()
    if datos is None:
        return None
    return _clasificar_en_datos(lat, lon, datos)


def clasificar(lat, lon) -> dict | None:
    """Clasificación corta del evento, o None si no hay datos/coordenadas."""
    try:
        latitud = float(str(lat).strip())
        longitud = float(str(lon).strip())
    except (TypeError, ValueError):
        return None
    if not (-90 <= latitud <= 90 and -180 <= longitud <= 180):
        return None
    try:
        return _clasificar_cache(round(latitud, 6), round(longitud, 6))
    except Exception:
        return None
