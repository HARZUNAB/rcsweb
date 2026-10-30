"""Pruebas del enlace al catálogo diario de sismologia.cl."""

from __future__ import annotations

from app.services.links import url_catalogo_dia


def test_url_dia_con_hora():
    assert url_catalogo_dia("2026-10-20 23:59:00") == (
        "https://www.sismologia.cl/sismicidad/catalogo/2026/10/20261020.html"
    )


def test_url_dia_iso_y_barras():
    esperada = (
        "https://www.sismologia.cl/sismicidad/catalogo/2025/07/20250705.html"
    )
    assert url_catalogo_dia("2025-07-05T10:00:00Z") == esperada
    assert url_catalogo_dia("2025/07/05 10:00:00") == esperada
    assert url_catalogo_dia("2025-07-05") == esperada


def test_url_dia_invalida():
    assert url_catalogo_dia("") is None
    assert url_catalogo_dia(None) is None
    assert url_catalogo_dia("sin fecha") is None
    assert url_catalogo_dia("2025-13-40") is None
