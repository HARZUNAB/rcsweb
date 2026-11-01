"""Genera el mini mapa de planta de los listados (``_mapa_chile.svg``).

El contorno de los países viene de Natural Earth 50m, que a 120x168 px se ve
más limpio que la capa 10m. Las divisiones regionales usan la capa 10m: los
polígonos rellenan cada región con un tono alternado y las líneas agregan el
borde segmentado. La proyección es lineal y debe coincidir exactamente con
``app.services.borders.posicion_mapa`` para que los marcadores de los eventos
caigan en el lugar correcto:

    x = (lon + 82) / 22 * 100
    y = (-14 - lat) / 42 * 140

Uso:
    CARTOPY_DATA_DIR=/ruta/a/cartopy python scripts/generar_mapa_chile.py

Si no se indica ``CARTOPY_DATA_DIR`` se usa el directorio de datos de Cartopy;
Natural Earth se descarga solo la primera vez. El resultado se escribe en
``app/templates/results/_mapa_chile.svg`` y se versiona en el repositorio.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import cartopy
import shapefile
from cartopy.io import shapereader
from shapely.geometry import box, shape
from shapely.ops import unary_union

LON_MIN, LON_MAX = -82.0, -60.0
LAT_MIN, LAT_MAX = -56.0, -14.0
ANCHO, ALTO = 100.0, 140.0

# Se recorta un grado más allá del viewBox para que los países vecinos no
# muestren un borde recto justo en el límite del mapa.
MARGEN = 1.0
BBOX = box(LON_MIN - MARGEN, LAT_MIN - MARGEN, LON_MAX + MARGEN, LAT_MAX + MARGEN)

PAISES_VECINOS = ("ARG", "PER", "BOL")
RESOLUCION_PAISES = "50m"
RESOLUCION_REGIONES = "10m"
TOLERANCIA_PAISES = 0.01
TOLERANCIA_REGIONES = 0.01
# Los rellenos regionales se simplifican más porque a 120 px no se distingue
# el detalle extra y así el SVG no crece de más.
TOLERANCIA_RELLENOS = 0.06
AREA_MINIMA = 0.002
# Solo las islas mayores conservan borde; el resto va con relleno para que el
# extremo sur no se convierta en una mancha oscura a este tamaño.
AREA_ISLA_BORDE = 0.6
TINTE_REGION_A = "#a9c6e9"
TINTE_REGION_B = "#d7e7f8"

RUTA_SALIDA = (
    Path(__file__).resolve().parent.parent
    / "app"
    / "templates"
    / "results"
    / "_mapa_chile.svg"
)


def _proyectar(lon: float, lat: float) -> tuple[float, float]:
    """Pasa longitud/latitud al sistema del SVG (viewBox 100x140)."""
    x = (lon - LON_MIN) / (LON_MAX - LON_MIN) * ANCHO
    y = (LAT_MAX - lat) / (LAT_MAX - LAT_MIN) * ALTO
    return x, y


def _partes(geometria):
    """Itera los polígonos de una geometría simple o múltiple."""
    if geometria.geom_type == "Polygon":
        return [geometria]
    return list(getattr(geometria, "geoms", []))


def _cargar(
    resolucion: str,
    categoria: str,
    nombre: str,
    codigos: set[str],
) -> dict:
    """Lee una capa de Natural Earth y une las geometrías por país."""
    ruta = shapereader.natural_earth(
        resolution=resolucion, category=categoria, name=nombre
    )
    lector = shapefile.Reader(ruta)
    campos = [campo[0] for campo in lector.fields[1:]]
    por_pais: dict[str, object] = {}
    for registro in lector.iterShapeRecords():
        if registro.shape.shapeType == 0 or not registro.shape.points:
            continue
        datos = dict(zip(campos, registro.record))
        codigo = datos.get("ADM0_A3")
        if codigo not in codigos:
            continue
        geometria = shape(registro.shape.__geo_interface__)
        if geometria.is_empty:
            continue
        if codigo in por_pais:
            geometria = unary_union([por_pais[codigo], geometria])
        por_pais[codigo] = geometria
    return por_pais


def _cargar_regiones() -> list:
    """Polígonos de las regiones de Chile (Natural Earth 10m)."""
    ruta = shapereader.natural_earth(
        resolution=RESOLUCION_REGIONES,
        category="cultural",
        name="admin_1_states_provinces",
    )
    lector = shapefile.Reader(ruta)
    campos = [campo[0] for campo in lector.fields[1:]]
    regiones = []
    for registro in lector.iterShapeRecords():
        if registro.shape.shapeType == 0 or not registro.shape.points:
            continue
        datos = dict(zip(campos, registro.record))
        if datos.get("adm0_a3") != "CHL":
            continue
        geometria = shape(registro.shape.__geo_interface__)
        if not geometria.is_empty:
            regiones.append(geometria)
    return regiones


def _poligonos_de(geometrias) -> list:
    """Aplana geometrías simples o múltiples y descarta fragmentos mínimos."""
    return [
        poligono
        for geometria in geometrias
        for poligono in _partes(geometria)
        if poligono.geom_type == "Polygon" and poligono.area >= AREA_MINIMA
    ]


def _datos_poligonos(geometrias) -> list:
    """Recorta, simplifica y filtra polígonos diminutos."""
    unida = unary_union(geometrias).intersection(BBOX)
    simplificada = unida.simplify(TOLERANCIA_PAISES, preserve_topology=True)
    return [
        poligono
        for poligono in _partes(simplificada)
        if poligono.geom_type == "Polygon" and poligono.area >= AREA_MINIMA
    ]


def _path_poligonos(poligonos) -> str:
    """Une varios polígonos (con sus huecos) en un único atributo ``d``."""
    trozos = []
    for poligono in poligonos:
        for anillo in [poligono.exterior, *poligono.interiors]:
            puntos = [
                f"{x:.1f},{y:.1f}"
                for x, y in (_proyectar(lon, lat) for lon, lat in anillo.coords)
            ]
            if len(puntos) >= 3:
                trozos.append("M " + " L ".join(puntos) + " Z")
    return " ".join(trozos)


def _path_lineas(geometria, recorte) -> str:
    """Convierte los límites regionales en subcaminos abiertos y recortados."""
    recortada = geometria.intersection(recorte).intersection(BBOX)
    simplificada = recortada.simplify(
        TOLERANCIA_REGIONES, preserve_topology=True
    )
    lineas = (
        [simplificada]
        if simplificada.geom_type == "LineString"
        else list(getattr(simplificada, "geoms", []))
    )
    trozos = []
    for linea in lineas:
        if linea.geom_type != "LineString" or len(linea.coords) < 2:
            continue
        puntos = [
            f"{x:.1f},{y:.1f}"
            for x, y in (_proyectar(lon, lat) for lon, lat in linea.coords)
        ]
        # El recorte deja fragmentos de un solo punto o de longitud cero; no
        # aportan nada y solo agrandan el SVG.
        if len(set(puntos)) < 2:
            continue
        trozos.append("M " + " L ".join(puntos))
    return " ".join(trozos)


def generar(salida: Path) -> Path:
    """Escribe el SVG y devuelve la ruta final."""
    paises = _cargar(
        RESOLUCION_PAISES,
        "cultural",
        "admin_0_countries",
        {"CHL", *PAISES_VECINOS},
    )
    regiones = _cargar(
        RESOLUCION_REGIONES,
        "cultural",
        "admin_1_states_provinces_lines",
        {"CHL"},
    )
    regiones_poligonos = _cargar_regiones()

    vecinos = _datos_poligonos(
        [paises[codigo] for codigo in PAISES_VECINOS if codigo in paises]
    )
    # El polígono de mayor área es el Chile continental; el resto son islas.
    chile = _datos_poligonos([paises["CHL"]])
    chile.sort(key=lambda poligono: poligono.area, reverse=True)
    continental, islas = chile[0], chile[1:]
    islas_mayores = [p for p in islas if p.area >= AREA_ISLA_BORDE]
    islas_menores = [p for p in islas if p.area < AREA_ISLA_BORDE]

    # Las regiones se recortan a Chile para que no crucen el mar ni Argentina.
    clip_regiones = paises["CHL"].buffer(0.03)
    rellenos = []
    for region in regiones_poligonos:
        recorte = region.intersection(paises["CHL"]).intersection(BBOX)
        if recorte.is_empty:
            continue
        rellenos.append(
            recorte.simplify(TOLERANCIA_RELLENOS, preserve_topology=True)
        )
    # De norte a sur y alternando dos tonos para distinguir regiones vecinas.
    rellenos.sort(key=lambda geometria: geometria.centroid.y, reverse=True)
    poligonos_a = _poligonos_de(rellenos[0::2])
    poligonos_b = _poligonos_de(rellenos[1::2])

    d_vecinos = _path_poligonos(vecinos)
    d_continente = _path_poligonos([continental])
    d_islas = _path_poligonos(islas_mayores)
    d_islas_menores = _path_poligonos(islas_menores)
    d_region_a = _path_poligonos(poligonos_a)
    d_region_b = _path_poligonos(poligonos_b)
    d_regiones = _path_lineas(
        unary_union(list(regiones.values())), clip_regiones
    )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" style="display: none" aria-hidden="true">
  <!-- Generado por scripts/generar_mapa_chile.py (Natural Earth 50m/10m).
       La proyeccion coincide con app/services/borders.posicion_mapa. -->
  <symbol id="mapa-chile-mini" viewBox="0 0 100 140"
          shape-rendering="geometricPrecision">
    <rect width="100" height="140" fill="#eef4fa"/>
    <path class="pais-vecino" fill="#e9edf1" stroke="#c8d2dc"
          stroke-width="0.35" fill-rule="evenodd" d="{d_vecinos}"/>
    <path class="pais-chile-base" fill="#b9d4f6" stroke="none"
          fill-rule="evenodd" d="{d_continente}"/>
    <path class="region-a" fill="{TINTE_REGION_A}" stroke="none"
          fill-rule="evenodd" d="{d_region_a}"/>
    <path class="region-b" fill="{TINTE_REGION_B}" stroke="none"
          fill-rule="evenodd" d="{d_region_b}"/>
    <path class="pais-chile-menor" fill="#b9d4f6" stroke="none"
          fill-rule="evenodd" d="{d_islas_menores}"/>
    <path class="pais-chile-casing" fill="none" stroke="#ffffff"
          stroke-width="3.0" stroke-linejoin="round" d="{d_continente}"/>
    <path class="pais-chile" fill="none" stroke="#1f2933"
          stroke-width="1.55" stroke-linejoin="round" fill-rule="evenodd"
          d="{d_continente}"/>
    <path class="pais-chile-islas" fill="#b9d4f6" stroke="#52606d"
          stroke-width="0.6" stroke-linejoin="round" fill-rule="evenodd"
          d="{d_islas}"/>
    <path class="region-chile" fill="none" stroke="#1f2933"
          stroke-width="0.85" stroke-dasharray="3 2"
          stroke-linecap="round" d="{d_regiones}"/>
  </symbol>
</svg>
"""
    salida.write_text(svg, encoding="utf-8")
    return salida


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Genera el mini mapa de planta de los listados."
    )
    parser.add_argument(
        "--datos",
        default=os.environ.get("CARTOPY_DATA_DIR"),
        help="Directorio de datos de Cartopy (o CARTOPY_DATA_DIR).",
    )
    parser.add_argument(
        "--salida",
        type=Path,
        default=RUTA_SALIDA,
        help="Ruta del SVG de salida.",
    )
    argumentos = parser.parse_args()
    if argumentos.datos:
        cartopy.config["data_dir"] = argumentos.datos

    ruta = generar(argumentos.salida)
    print(f"Mapa generado: {ruta} ({ruta.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
