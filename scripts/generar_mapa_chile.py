"""Genera el mini mapa de planta de los listados (``_mapa_chile.svg``).

El mapa usa Natural Earth 10m: países vecinos, contorno de Chile (continental
e islas) y los límites internos de las regiones. La proyección es lineal y debe
coincidir exactamente con ``app.services.borders.posicion_mapa`` para que los
marcadores de los eventos caigan en el lugar correcto:

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
TOLERANCIA_PAISES = 0.04
TOLERANCIA_REGIONES = 0.01
AREA_MINIMA = 0.002
TOLERANCIA_ISLAS = 0.01

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


def _cargar(categoria: str, nombre: str, codigos: set[str]) -> dict:
    """Lee una capa de Natural Earth y une las geometrías por país."""
    ruta = shapereader.natural_earth(
        resolution="10m", category=categoria, name=nombre
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


def _path_lineas(geometria) -> str:
    """Convierte los límites regionales en subcaminos abiertos."""
    recortada = geometria.intersection(BBOX)
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
        trozos.append("M " + " L ".join(puntos))
    return " ".join(trozos)


def generar(salida: Path) -> Path:
    """Escribe el SVG y devuelve la ruta final."""
    paises = _cargar(
        "cultural",
        "admin_0_countries",
        {"CHL", *PAISES_VECINOS},
    )
    regiones = _cargar(
        "cultural", "admin_1_states_provinces_lines", {"CHL"}
    )

    vecinos = _datos_poligonos(
        [paises[codigo] for codigo in PAISES_VECINOS if codigo in paises]
    )
    # El polígono de mayor área es el Chile continental; el resto son islas.
    chile = _datos_poligonos([paises["CHL"]])
    chile.sort(key=lambda poligono: poligono.area, reverse=True)
    continental, islas = chile[0], chile[1:]
    islas_mayores = [p for p in islas if p.area >= TOLERANCIA_ISLAS]
    islas_menores = [p for p in islas if p.area < TOLERANCIA_ISLAS]

    d_vecinos = _path_poligonos(vecinos)
    d_continente = _path_poligonos([continental])
    d_islas = _path_poligonos(islas_mayores)
    d_islas_menores = _path_poligonos(islas_menores)
    d_regiones = _path_lineas(unary_union(list(regiones.values())))

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" style="display: none" aria-hidden="true">
  <!-- Generado por scripts/generar_mapa_chile.py (Natural Earth 10m).
       La proyeccion coincide con app/services/borders.posicion_mapa. -->
  <symbol id="mapa-chile-mini" viewBox="0 0 100 140"
          shape-rendering="geometricPrecision">
    <rect width="100" height="140" fill="#eef4fa"/>
    <path class="pais-vecino" fill="#e9edf1" stroke="#b6bfc8"
          stroke-width="0.3" fill-rule="evenodd" d="{d_vecinos}"/>
    <path class="pais-chile-menor" fill="#b9d4f6" stroke="none"
          fill-rule="evenodd" d="{d_islas_menores}"/>
    <path class="pais-chile-islas" fill="#b9d4f6" stroke="#52606d"
          stroke-width="0.4" stroke-linejoin="round" fill-rule="evenodd"
          d="{d_islas}"/>
    <path class="pais-chile" fill="#b9d4f6" stroke="#1f2933"
          stroke-width="0.8" stroke-linejoin="round" fill-rule="evenodd"
          d="{d_continente}"/>
    <path class="region-chile" fill="none" stroke="#202020"
          stroke-width="0.45" stroke-dasharray="1.6 1.2"
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
