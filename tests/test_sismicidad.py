"""Pruebas de la clasificación de eventos sospechosos del core."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import numpy as np

CORE = Path(__file__).resolve().parents[1] / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import sismicidad  # noqa: E402


def _catalogo(xs, profs):
    xs = np.array(xs, dtype=float)
    profs = np.array(profs, dtype=float)
    return {
        "x": xs,
        "y": np.zeros(len(xs)),
        "prof": profs,
        "lat": np.zeros(len(xs)),
        "lon": np.zeros(len(xs)),
        "lat_ref": 0.0,
        "lon_ref": 0.0,
    }


def _evento(**cambios):
    base = {
        "id": "e1",
        "latitud": 0.0,
        "longitud": 0.0,
        "prof": 165.0,
        "perp_km": 42.0,
        "residuo_km": 44.0,
        "dist_asoc": 60.0,
        "perfil": "P001",
    }
    base.update(cambios)
    return base


def _criterios(**cambios_veto):
    criterios = copy.deepcopy(sismicidad.CRITERIOS_SOSPECHOSO)
    criterios["veto_tendencia"].update(cambios_veto)
    return criterios


def test_veto_por_tendencia_no_marca_un_evento_alineado():
    catalogo = _catalogo([16, 17, 18, 19, 20], [160, 165, 170, 175, 168])

    resultado = sismicidad.evaluar(
        _evento(), catalogo, _criterios(activo=True)
    )

    assert resultado["sospechoso"] is False
    assert resultado["vetado_por_tendencia"] is True
    assert resultado["metricas"]["tendencia_vecinos"] == 5
    assert resultado["metricas"]["tendencia_mediana_km"] == 168.0


def test_veto_desactivado_mantiene_la_clasificacion_anterior():
    catalogo = _catalogo([16, 17, 18, 19, 20], [160, 165, 170, 175, 168])

    resultado = sismicidad.evaluar(
        _evento(), catalogo, _criterios(activo=False)
    )

    assert resultado["sospechoso"] is True
    assert resultado["vetado_por_tendencia"] is False


def test_evento_que_se_desvia_de_la_mediana_sigue_sospechoso():
    catalogo = _catalogo([16, 17, 18, 19, 20], [160, 165, 170, 175, 168])

    resultado = sismicidad.evaluar(
        _evento(prof=220.0), catalogo, _criterios(activo=True)
    )

    assert resultado["sospechoso"] is True
    assert resultado["vetado_por_tendencia"] is False


def test_evento_aislado_no_se_veta_por_tendencia():
    catalogo = _catalogo([30, 31, 32, 33, 34], [160, 165, 170, 175, 168])

    resultado = sismicidad.evaluar(
        _evento(), catalogo, _criterios(activo=True)
    )

    assert resultado["sospechoso"] is True
    assert resultado["vetado_por_tendencia"] is False
    assert resultado["metricas"]["tendencia_vecinos"] == 0


def test_evento_sin_perfil_sigue_siendo_sospechoso():
    catalogo = _catalogo([16, 17, 18, 19, 20], [160, 165, 170, 175, 168])

    resultado = sismicidad.evaluar(
        _evento(perfil=None), catalogo, _criterios(activo=True)
    )

    assert resultado["sospechoso"] is True
    assert resultado["sin_perfil"] is True
    assert resultado["vetado_por_tendencia"] is False
