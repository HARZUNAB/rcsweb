#!/usr/bin/env python3
"""
fronteras.py
============
Distancia de un evento a la frontera terrestre chilena más cercana.

Se usan las líneas de frontera de Natural Earth 10m y el polígono de Chile de
la misma fuente. Solo interesan las fronteras con Perú, Bolivia y Argentina.
Los datos se cargan una vez y se cachean; la distancia por coordenada también
se cachea, porque los listados la consultan para cada fila.

La función principal devuelve None cuando el punto está dentro de Chile, en
mar chileno (aproximado con 200 millas náuticas desde la costa), no tiene
coordenadas válidas o no se pudo cargar Natural Earth. En esos casos la
interfaz muestra «—» o simplemente omite la línea.
"""

import math
from functools import lru_cache

PAISES = {
    "PER": "Perú",
    "BOL": "Bolivia",
    "ARG": "Argentina",
}

# Aproximación de mar chileno: 200 millas náuticas desde la costa. No es el
# límite oficial de la ZEE, pero evita mostrar una frontera terrestre para
# eventos claramente costeros.
RADIO_MAR_CHILENO_KM = 200.0 * 1.852

_CACHE_DATOS = None
_CACHE_ERROR = False
_GEOD = None


def limpiar_cache():
    """Olvida geometrías y distancias calculadas (útil en pruebas)."""
    global _CACHE_DATOS, _CACHE_ERROR, _GEOD
    _CACHE_DATOS = None
    _CACHE_ERROR = False
    _GEOD = None
    _frontera_cache.cache_clear()


def _geod():
    global _GEOD
    if _GEOD is None:
        from pyproj import Geod
        _GEOD = Geod(ellps="WGS84")
    return _GEOD


def _cargar_datos():
    """Carga (una vez) las fronteras y el polígono de Chile."""
    global _CACHE_DATOS, _CACHE_ERROR
    if _CACHE_DATOS is not None:
        return _CACHE_DATOS
    if _CACHE_ERROR:
        return None
    try:
        import shapefile
        from shapely.geometry import shape
        from shapely.ops import unary_union
        from shapely.prepared import prep
        from cartopy.io import shapereader

        ruta_lineas = shapereader.natural_earth(
            resolution="10m", category="cultural",
            name="admin_0_boundary_lines_land")
        lector = shapefile.Reader(ruta_lineas)
        campos = [f[0] for f in lector.fields[1:]]
        fronteras = {}
        for registro in lector.iterShapeRecords():
            datos = dict(zip(campos, registro.record))
            izquierda = datos.get("ADM0_A3_L")
            derecha = datos.get("ADM0_A3_R")
            if izquierda == "CHL" and derecha in PAISES:
                vecino = derecha
            elif derecha == "CHL" and izquierda in PAISES:
                vecino = izquierda
            else:
                continue
            if (registro.shape.shapeType == 0
                    or not registro.shape.points):
                continue
            geom = shape(registro.shape.__geo_interface__)
            if not geom.is_empty:
                fronteras.setdefault(vecino, []).append(geom)

        ruta_paises = shapereader.natural_earth(
            resolution="10m", category="cultural",
            name="admin_0_countries")
        lector = shapefile.Reader(ruta_paises)
        campos = [f[0] for f in lector.fields[1:]]
        partes = {"CHL": [], "PER": [], "BOL": [], "ARG": []}
        for registro in lector.iterShapeRecords():
            datos = dict(zip(campos, registro.record))
            codigo = datos.get("ADM0_A3")
            if codigo not in partes:
                continue
            if (registro.shape.shapeType == 0
                    or not registro.shape.points):
                continue
            partes[codigo].append(
                shape(registro.shape.__geo_interface__))
        if not partes["CHL"] or not fronteras:
            raise ValueError("Natural Earth no trajo Chile o sus fronteras")
        paises = {}
        for codigo, geoms in partes.items():
            if not geoms:
                raise ValueError("Natural Earth no trajo %s" % codigo)
            geom = unary_union(geoms)
            if not geom.is_valid:
                geom = geom.buffer(0)
            paises[codigo] = geom
        prep_paises = {codigo: prep(geom)
                       for codigo, geom in paises.items()}
        _CACHE_DATOS = (fronteras, paises, prep_paises)
    except Exception:
        _CACHE_ERROR = True
        _CACHE_DATOS = None
    return _CACHE_DATOS


def _distancia_tierra_km(lon, lat, punto, geom):
    """Distancia geodésica al punto más cercano de una geometría de tierra."""
    from shapely.ops import nearest_points

    cercano = nearest_points(punto, geom)[1]
    _, _, distancia = _geod().inv(lon, lat, cercano.x, cercano.y)
    return distancia / 1000.0


def _es_mar_chileno(lon, lat, punto, paises, prep_paises):
    """
    True si el punto está en mar chileno, según la aproximación de 200 mn.

    Solo se evalúa fuera de tierra. Si está dentro de Perú, Bolivia o
    Argentina, no es mar chileno. En el mar, se compara qué territorio está
    más cerca y se exige que sea Chile y que no supere el radio de 200 mn.
    """
    for codigo in ("PER", "BOL", "ARG"):
        if prep_paises[codigo].contains(punto):
            return False

    distancia_chile = _distancia_tierra_km(
        lon, lat, punto, paises["CHL"])
    if distancia_chile > RADIO_MAR_CHILENO_KM:
        return False

    mejor_codigo = "CHL"
    mejor_distancia = distancia_chile
    for codigo in ("PER", "BOL", "ARG"):
        distancia = _distancia_tierra_km(
            lon, lat, punto, paises[codigo])
        if distancia < mejor_distancia:
            mejor_distancia = distancia
            mejor_codigo = codigo
    return mejor_codigo == "CHL"


def _frontera_en_datos(lat, lon, datos):
    """Cálculo puro sobre las geometrías ya cargadas."""
    from shapely.geometry import Point
    from shapely.ops import nearest_points

    fronteras, paises, prep_paises = datos
    punto = Point(lon, lat)
    if prep_paises["CHL"].contains(punto):
        return None
    if _es_mar_chileno(lon, lat, punto, paises, prep_paises):
        return None

    mejor = None
    for codigo, geometrias in fronteras.items():
        for geom in geometrias:
            cercano = nearest_points(punto, geom)[1]
            _, _, distancia = _geod().inv(
                lon, lat, cercano.x, cercano.y)
            if mejor is None or distancia < mejor[0]:
                mejor = (distancia, codigo)
    if mejor is None:
        return None
    return PAISES.get(mejor[1], mejor[1]), round(mejor[0] / 1000.0, 1)


@lru_cache(maxsize=8192)
def _frontera_cache(lat, lon):
    datos = _cargar_datos()
    if datos is None:
        return None
    return _frontera_en_datos(lat, lon, datos)


def frontera_mas_cercana(lat, lon):
    """
    Devuelve (país, km) de la frontera chilena terrestre más cercana.

    Devuelve None si el punto está dentro de Chile, en mar chileno (aprox.
    200 millas náuticas de la costa), las coordenadas son inválidas o no se
    pudo cargar Natural Earth.
    """
    try:
        lat = float(str(lat).strip())
        lon = float(str(lon).strip())
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return _frontera_cache(round(lat, 6), round(lon, 6))


def formatear_frontera(resultado):
    """Texto legible de (país, km), o «—» si no hay dato."""
    if not resultado:
        return "—"
    pais, km = resultado
    try:
        return "%s — %.1f km" % (pais, float(km))
    except (TypeError, ValueError):
        return "—"


def texto_frontera_coords(lat, lon):
    """Texto de la frontera para coordenadas sueltas; «—» si no aplica."""
    return formatear_frontera(frontera_mas_cercana(lat, lon))


def anotar_fila(fila, clave_lat="latitud", clave_lon="longitud"):
    """Agrega Frontera_pais/Frontera_km a un dict de evento."""
    if "Frontera_pais" in fila and "Frontera_km" in fila:
        return fila
    resultado = frontera_mas_cercana(
        fila.get(clave_lat), fila.get(clave_lon))
    if resultado is None:
        fila["Frontera_pais"] = ""
        fila["Frontera_km"] = None
    else:
        fila["Frontera_pais"], fila["Frontera_km"] = resultado
    return fila


def anotar_filas(filas, clave_lat="latitud", clave_lon="longitud"):
    """Anota una lista de filas, sin recalcular al filtrar u ordenar."""
    for fila in filas:
        anotar_fila(fila, clave_lat=clave_lat, clave_lon=clave_lon)
    return filas


def texto_frontera(fila):
    """Texto de la columna Frontera para una fila ya anotada."""
    pais = fila.get("Frontera_pais") or ""
    km = fila.get("Frontera_km")
    if not pais or km in (None, ""):
        return "—"
    try:
        return "%s — %.1f km" % (pais, float(km))
    except (TypeError, ValueError):
        return "—"
