"""Pruebas de la clasificación geográfica de los listados."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from shapely.geometry import box
from shapely.ops import unary_union
from shapely.prepared import prep

from app.services import ubicacion as ubi


@pytest.fixture(autouse=True)
def _cache_limpia():
    ubi.limpiar_cache()
    yield
    ubi.limpiar_cache()


def _datos():
    continental = box(-75.0, -30.0, -69.0, -20.0)
    isla = box(-80.0, -28.0, -79.0, -27.0)
    chile = unary_union([continental, isla])
    peru = box(-69.0, -30.0, -65.0, -20.0)
    argentina = box(-65.0, -30.0, -55.0, -20.0)
    brasil = box(-55.0, -30.0, -45.0, -20.0)
    tierra = [box(-80.0, -31.0, -45.0, -19.0)]
    modulo = SimpleNamespace(
        PAISES={
            "CHL": "Chile",
            "PER": "Perú",
            "BOL": "Bolivia",
            "ARG": "Argentina",
        },
        RADIO_MAR_CHILENO_KM=370.0,
    )
    return {
        "modulo": modulo,
        "chile": chile,
        "continental": continental,
        "insular": isla,
        "prep_chile": prep(chile),
        "prep_continental": prep(continental),
        "prep_insular": prep(isla),
        "vecinos": [("PER", peru), ("ARG", argentina)],
        "prep_vecinos": [("PER", prep(peru)), ("ARG", prep(argentina))],
        "otros": [("BRA", "Brasil", brasil, prep(brasil))],
        "tierra": tierra,
    }


def test_chile_continental():
    datos = ubi._clasificar_en_datos(-25.0, -70.0, _datos())

    assert datos["ambito"] == "chile_continental"
    assert datos["texto"] == "Chile · continental"


def test_chile_insular():
    datos = ubi._clasificar_en_datos(-27.5, -79.5, _datos())

    assert datos["ambito"] == "chile_insular"
    assert datos["texto"] == "Chile · insular"


def test_pais_vecino(monkeypatch):
    monkeypatch.setattr(ubi, "_km_frontera", lambda lat, lon: 50.0)

    datos = ubi._clasificar_en_datos(-25.0, -67.0, _datos())

    assert datos["ambito"] == "pais"
    assert datos["texto"] == "Perú"
    assert "frontera 50 km" in datos["detalle"]


def test_otro_pais(monkeypatch):
    monkeypatch.setattr(ubi, "_km_frontera", lambda lat, lon: 1200.0)

    datos = ubi._clasificar_en_datos(-25.0, -50.0, _datos())

    assert datos["ambito"] == "pais"
    assert datos["texto"] == "Brasil"


def test_mar_chileno():
    datos = ubi._clasificar_en_datos(-25.0, -76.0, _datos())

    assert datos["ambito"] == "mar_chileno"
    assert datos["texto"] == "Mar chileno"
    assert "costa afuera" in datos["detalle"]


def test_costa_cerca_del_borde():
    datos = ubi._clasificar_en_datos(-25.0, -75.01, _datos())

    assert datos["ambito"] == "chile_costa"
    assert datos["texto"] == "Chile · costa"


def test_alta_mar():
    datos = ubi._clasificar_en_datos(-25.0, -95.0, _datos())

    assert datos["ambito"] == "alta_mar"
    assert datos["texto"] == "Alta mar"


def test_clasificar_coordenadas_invalidas():
    assert ubi.clasificar("", -70.0) is None
    assert ubi.clasificar(100.0, -70.0) is None


def test_clasificar_sin_capas(monkeypatch):
    monkeypatch.setattr(ubi, "_cargar_datos", lambda: None)

    assert ubi.clasificar(-33.45, -70.65) is None
