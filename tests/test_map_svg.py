"""Pruebas del mini mapa de planta generado desde Natural Earth 10m."""

from __future__ import annotations

import re
from pathlib import Path

RUTA = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "templates"
    / "results"
    / "_mapa_chile.svg"
)


def _svg() -> str:
    return RUTA.read_text(encoding="utf-8")


def test_mapa_conserva_symbol_y_proyeccion():
    svg = _svg()
    assert 'id="mapa-chile-mini"' in svg
    assert 'viewBox="0 0 100 140"' in svg
    # La proyección del script debe ser la misma que usa posicion_mapa.
    assert "borders.posicion_mapa" in svg


def test_mapa_tiene_chile_vecinos_y_regiones():
    svg = _svg()
    assert 'class="pais-vecino"' in svg
    assert 'class="pais-chile"' in svg
    assert 'class="pais-chile-islas"' in svg
    assert 'class="region-chile"' in svg
    # Las regiones se dibujan con línea segmentada y más fina que el borde
    # nacional, para que la jerarquía visual quede clara.
    region = re.search(r'class="region-chile"[^>]*', svg).group(0)
    assert 'stroke-dasharray="1.6 1.2"' in region
    assert 'stroke-width="0.45"' in region
    nacional = re.search(r'class="pais-chile" fill[^>]*', svg).group(0)
    assert 'stroke-width="0.8"' in nacional


def test_mapa_incluye_detalle_de_islas():
    svg = _svg()
    d = re.search(r'class="pais-chile" fill[^>]*\sd="([^"]*)"', svg).group(1)
    assert d.count("M ") >= 1
    # El contorno continental es mucho más detallado que el mapa anterior.
    assert len(d) > 5000
    islas = re.search(
        r'class="pais-chile-islas"[^>]*\sd="([^"]*)"', svg
    ).group(1)
    assert islas.count("M ") > 10


def test_mapa_no_se_sale_del_area_con_margen():
    svg = _svg()
    for d in re.findall(r'\sd="([^"]*)"', svg):
        for x, y in re.findall(r"(-?\d+\.\d),(-?\d+\.\d)", d):
            assert -10 <= float(x) <= 110
            assert -10 <= float(y) <= 150
