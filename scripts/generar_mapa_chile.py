"""Divisiones regionales del mini mapa y datos para los paneles.

El mini mapa base (``app/templates/results/_mapa_chile.svg``) se conserva tal
como estaba: países vecinos, relleno de Chile y su contorno original a 90x130.
Este script solo agrega (o reemplaza) la capa ``region-chile`` con los límites
regionales de Natural Earth 10m, recortados al contorno de Chile del propio SVG.

Además genera ``app/static/data/chile_regiones.json`` con el contorno de Chile
y las líneas regionales en longitud/latitud. Los paneles usan ese archivo para
dibujar una capa vectorial discreta sobre el mapa de Plotly.

La proyección es lineal y coincide con ``app.services.borders.posicion_mapa``:

    x = (lon + 82) / 22 * 100
    y = (-14 - lat) / 42 * 140

Uso:
    CARTOPY_DATA_DIR=/ruta/a/cartopy python scripts/generar_mapa_chile.py

Cartopy descarga Natural Earth la primera vez si no está en el directorio de
datos. No se modifica el proyecto base.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

import cartopy
import shapefile
from cartopy.io import shapereader
from shapely.geometry import LineString, Polygon, box, shape
from shapely.ops import unary_union

LON_MIN, LON_MAX = -82.0, -60.0
LAT_MIN, LAT_MAX = -56.0, -14.0
ANCHO, ALTO = 100.0, 140.0

# Mismo recorte que el mini mapa: deja fuera el reclamo antártico, que no
# aporta regiones y alargaría el JSON y el dibujo sin necesidad.
BBOX = box(LON_MIN - 1, LAT_MIN - 1, LON_MAX + 1, LAT_MAX + 1)

RESOLUCION_PAISES = "50m"
RESOLUCION_REGIONES = "10m"
TOLERANCIA_REGIONES = 0.01
TOLERANCIA_SVG = 0.15
TOLERANCIA_JSON = 0.01

RUTA_SALIDA = (
    Path(__file__).resolve().parent.parent
    / "app"
    / "templates"
    / "results"
    / "_mapa_chile.svg"
)
RUTA_JSON = (
    Path(__file__).resolve().parent.parent
    / "app"
    / "static"
    / "data"
    / "chile_regiones.json"
)


def _proyectar(lon: float, lat: float) -> tuple[float, float]:
    """Pasa longitud/latitud al sistema del SVG (viewBox 100x140)."""
    x = (lon - LON_MIN) / (LON_MAX - LON_MIN) * ANCHO
    y = (LAT_MAX - lat) / (LAT_MAX - LAT_MIN) * ALTO
    return x, y


def _partes(geometria):
    """Itera polígonos o líneas de una geometría simple o múltiple."""
    if geometria.geom_type in {"Polygon", "LineString"}:
        return [geometria]
    return list(getattr(geometria, "geoms", []))


def _cargar_paises(codigos: set[str]) -> dict:
    """Une las geometrías de los países indicados."""
    ruta = shapereader.natural_earth(
        resolution=RESOLUCION_PAISES,
        category="cultural",
        name="admin_0_countries",
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


def _cargar_regiones():
    """Límites internos de las regiones de Chile (Natural Earth 10m)."""
    ruta = shapereader.natural_earth(
        resolution=RESOLUCION_REGIONES,
        category="cultural",
        name="admin_1_states_provinces_lines",
    )
    lector = shapefile.Reader(ruta)
    campos = [campo[0] for campo in lector.fields[1:]]
    regiones = []
    for registro in lector.iterShapeRecords():
        if registro.shape.shapeType == 0 or not registro.shape.points:
            continue
        datos = dict(zip(campos, registro.record))
        if datos.get("ADM0_A3") != "CHL":
            continue
        geometria = shape(registro.shape.__geo_interface__)
        if not geometria.is_empty:
            regiones.append(geometria)
    return unary_union(regiones)


def _poligonos_svg(path: str) -> list[Polygon]:
    """Reconstruye los polígonos del contorno de Chile desde el atributo d."""
    poligonos = []
    for tramo in path.split(" M "):
        puntos = [
            (float(x), float(y))
            for x, y in re.findall(r"(-?\d+\.?\d*),(-?\d+\.?\d*)", tramo)
        ]
        if len(puntos) >= 3:
            poligonos.append(Polygon(puntos))
    return poligonos


def _path_regiones_svg(lineas, contorno) -> str:
    """Proyecta, recorta y simplifica las regiones en coordenadas del SVG."""
    recortadas = []
    for linea in _partes(lineas):
        if linea.geom_type != "LineString" or len(linea.coords) < 2:
            continue
        puntos = [_proyectar(lon, lat) for lon, lat in linea.coords]
        recorte = LineString(puntos).intersection(contorno)
        if recorte.is_empty:
            continue
        recortadas.append(
            recorte.simplify(TOLERANCIA_SVG, preserve_topology=True)
        )
    trozos = []
    for geometria in recortadas:
        for linea in _partes(geometria):
            if linea.geom_type != "LineString" or len(linea.coords) < 2:
                continue
            puntos = [
                f"{x:.1f},{y:.1f}" for x, y in linea.coords
            ]
            if len(set(puntos)) < 2:
                continue
            trozos.append("M " + " L ".join(puntos))
    return " ".join(trozos)


def _lineas_json(geometrias, cerrar: bool = False) -> dict:
    """Convierte líneas o anillos en listas lon/lat con separadores None."""
    lons: list[float | None] = []
    lats: list[float | None] = []
    for geometria in geometrias:
        for parte in _partes(geometria):
            if parte.geom_type == "Polygon":
                anillos = [parte.exterior, *parte.interiors]
            elif parte.geom_type == "LineString":
                anillos = [parte]
            else:
                continue
            for anillo in anillos:
                puntos = list(anillo.coords)
                if len(puntos) < 2:
                    continue
                if lons:
                    lons.append(None)
                    lats.append(None)
                for lon, lat in puntos:
                    lons.append(round(lon, 3))
                    lats.append(round(lat, 3))
                if cerrar and puntos[0] != puntos[-1]:
                    lons.append(round(puntos[0][0], 3))
                    lats.append(round(puntos[0][1], 3))
    return {"lon": lons, "lat": lats}


def generar_svg(salida: Path) -> Path:
    """Agrega la capa regional al SVG base y devuelve la ruta."""
    svg = salida.read_text(encoding="utf-8")
    # Idempotente: si ya existe una capa regional, se reemplaza.
    svg = re.sub(
        r'\s*<path class="region-chile".*?/>', "", svg, flags=re.S
    )
    if "borders.posicion_mapa" not in svg:
        svg = svg.replace(
            "  <symbol",
            "  <!-- Proyeccion: app/services/borders.posicion_mapa -->\n"
            "  <symbol",
            1,
        )

    coincidencia = re.search(
        r'class="pais-chile"[^>]*?\sd="([^"]*)"', svg, re.S
    )
    if not coincidencia:
        raise ValueError("El SVG base no tiene el contorno class=pais-chile")
    contorno = unary_union(_poligonos_svg(coincidencia.group(1))).buffer(0.2)

    regiones = _cargar_regiones()
    d_regiones = _path_regiones_svg(regiones, contorno)
    capa = (
        '    <path class="region-chile" fill="none" stroke="#52606d"\n'
        '          stroke-width="0.5" stroke-dasharray="1.8 1.2"\n'
        f'          stroke-linecap="round" d="{d_regiones}"/>\n'
    )
    svg = svg.replace("  </symbol>", capa + "  </symbol>", 1)
    salida.write_text(svg, encoding="utf-8")
    return salida


def generar_json(salida: Path) -> Path:
    """Genera el contorno y las regiones en lon/lat para los paneles."""
    paises = _cargar_paises({"CHL"})
    contorno = paises["CHL"].intersection(BBOX).simplify(
        TOLERANCIA_JSON, preserve_topology=True
    )
    regiones = _cargar_regiones().intersection(BBOX).simplify(
        TOLERANCIA_JSON, preserve_topology=True
    )
    datos = {
        "contorno": _lineas_json([contorno], cerrar=True),
        "regiones": _lineas_json([regiones]),
    }
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(
        json.dumps(datos, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return salida


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Agrega las regiones al mini mapa y genera el JSON."
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
        help="Ruta del SVG del mini mapa.",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=RUTA_JSON,
        help="Ruta del JSON de contorno y regiones para los paneles.",
    )
    argumentos = parser.parse_args()
    if argumentos.datos:
        cartopy.config["data_dir"] = argumentos.datos

    svg = generar_svg(argumentos.salida)
    datos = generar_json(argumentos.json)
    print(f"Mini mapa: {svg} ({svg.stat().st_size} bytes)")
    print(f"Datos de paneles: {datos} ({datos.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
