"""Pruebas del fondo de sismicidad histórica."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from app.services import history


def _fake_plotear(lats, lons, profs, alongs=None, profs_perfil=None):
    return SimpleNamespace(
        HIST_LABEL="Sismicidad histórica de prueba",
        _cargar_sismicidad=lambda: (
            np.asarray(lats, dtype=float),
            np.asarray(lons, dtype=float),
            np.asarray(profs, dtype=float),
        ),
        _proyectar_hist_perfil=lambda lons_, lats_, profs_, perfil: (
            alongs if alongs is not None else [0.0, 10.0],
            profs_perfil if profs_perfil is not None else [-10.0, -20.0],
        ),
    )


def test_perfil_proyecta_y_cachea(monkeypatch):
    history._CACHE_PERFIL.clear()
    llamadas = []

    def proyectar(lons, lats, profs, perfil):
        llamadas.append(perfil["id"])
        return [1.0, 2.0], [-3.0, -4.0]

    fake = _fake_plotear([0], [0], [0])
    fake._proyectar_hist_perfil = proyectar
    monkeypatch.setattr(history, "_plotear", lambda: fake)
    perfil_datos = {
        "id": "P1",
        "slab_lon": [-70.0, -69.0],
        "slab_lat": [-30.0, -29.0],
        "slab_p": [0.0, 10.0],
    }

    primero = history.perfil(perfil_datos)
    segundo = history.perfil(perfil_datos)

    assert primero["along"] == [1.0, 2.0]
    assert primero["prof"] == [-3.0, -4.0]
    assert primero["total"] == 2
    assert segundo == primero
    assert llamadas == ["P1"]


def test_perfil_sin_slab_devuelve_vacio():
    assert history.perfil({"id": "P1", "slab_lon": [], "slab_lat": [], "slab_p": []}) == {
        "along": [],
        "prof": [],
        "total": 0,
    }


def test_datos_incluye_etiqueta(monkeypatch):
    history._CACHE_PERFIL.clear()
    monkeypatch.setattr(history, "_plotear", lambda: _fake_plotear([0], [0], [0]))
    datos = history.datos(
        {
            "id": "P1",
            "slab_lon": [-70.0, -69.0],
            "slab_lat": [-30.0, -29.0],
            "slab_p": [0.0, 10.0],
        },
    )
    assert datos["label"] == "Sismicidad histórica de prueba"
    assert "planta" not in datos
    assert datos["perfil"]["total"] == 2
