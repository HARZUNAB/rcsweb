"""Pruebas del mini mapa de planta y de los datos regionales de los paneles."""

from __future__ import annotations

import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
RUTA = RAIZ / "app" / "templates" / "results" / "_mapa_chile.svg"
RUTA_JSON = RAIZ / "app" / "static" / "data" / "chile_regiones.json"


def _svg() -> str:
    return RUTA.read_text(encoding="utf-8")


def test_mapa_conserva_symbol_y_proyeccion():
    svg = _svg()
    assert 'id="mapa-chile-mini"' in svg
    assert 'viewBox="0 0 100 140"' in svg
    # La proyección del script debe ser la misma que usa posicion_mapa.
    assert "borders.posicion_mapa" in svg


def test_mapa_conserva_el_estilo_original():
    svg = _svg()
    assert 'class="pais-vecino"' in svg
    assert 'stroke="#a9b3bd"' in svg
    # El relleno y el borde son los del mapa original, sin halos ni rellenos
    # regionales que cambien el aspecto.
    chile = re.search(r'class="pais-chile" fill[^>]*', svg).group(0)
    assert 'fill="#b9d4f6"' in chile
    assert 'stroke="#52606d"' in chile
    assert 'stroke-width="0.55"' in chile
    assert 'class="region-a"' not in svg
    assert 'class="region-b"' not in svg
    assert 'pais-chile-casing' not in svg


def test_mapa_tiene_divisiones_regionales_discretas():
    svg = _svg()
    region = re.search(r'class="region-chile"[^>]*', svg).group(0)
    assert 'fill="none"' in region
    assert 'stroke="#52606d"' in region
    assert 'stroke-width="0.5"' in region
    assert 'stroke-dasharray="1.8 1.2"' in region


def test_mapa_conserva_el_detalle_del_contorno():
    svg = _svg()
    d = re.search(r'class="pais-chile"[^>]*?\sd="([^"]*)"', svg, re.S).group(1)
    assert len(d) > 5000
    assert d.count("M ") >= 20


def test_mapa_no_se_sale_del_area_con_margen():
    svg = _svg()
    for d in re.findall(r'\sd="([^"]*)"', svg):
        for x, y in re.findall(r"(-?\d+\.\d+),(-?\d+\.\d+)", d):
            assert -10 <= float(x) <= 110
            assert -10 <= float(y) <= 150


def test_json_regiones_para_los_paneles():
    datos = json.loads(RUTA_JSON.read_text(encoding="utf-8"))
    assert set(datos) == {"contorno", "regiones"}
    for clave in ("contorno", "regiones"):
        assert len(datos[clave]["lon"]) == len(datos[clave]["lat"])
        assert len(datos[clave]["lon"]) > 100
    # Los tramos se separan con null para que Plotly no una líneas distintas.
    assert datos["regiones"]["lon"].count(None) >= 10
    assert datos["regiones"]["lat"].count(None) >= 10


def test_json_regiones_dentro_del_area_de_chile():
    datos = json.loads(RUTA_JSON.read_text(encoding="utf-8"))
    for clave in ("contorno", "regiones"):
        for lon in datos[clave]["lon"]:
            if lon is not None:
                assert -82 <= lon <= -60
        for lat in datos[clave]["lat"]:
            if lat is not None:
                assert -57 <= lat <= -14
