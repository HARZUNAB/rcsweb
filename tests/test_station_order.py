"""Pruebas del orden por llegada en los listados de arribos."""

from __future__ import annotations

from datetime import datetime

from app.services.station_review import _agrupar, _datos_mapa_tiempos


def _fila(estacion, fase, instante, usada=True):
    return {
        "red": "C1",
        "estacion": estacion,
        "fase": fase,
        "llegada": instante.strftime("%Y-%m-%d %H:%M:%S.%f"),
        "_llegada": instante,
        "_usada": usada,
        "_azimut": 0.0,
    }


def test_agrupar_ordena_por_primera_llegada_y_fases():
    filas = [
        _fila("MG04", "P", datetime(2026, 10, 28, 15, 27, 41, 921878)),
        _fila("MG03", "P", datetime(2026, 10, 28, 15, 27, 41, 512964)),
        _fila("MG04", "S", datetime(2026, 10, 28, 15, 27, 55, 100000)),
    ]

    grupos = _agrupar(filas)

    assert [grupo["estacion"] for grupo in grupos] == ["MG03", "MG04"]
    assert [fila["fase"] for fila in grupos[1]["filas"]] == ["P", "S"]
    assert grupos[1]["llegada"] == "15:27:41"


def test_mapa_ordena_arribos_por_llegada_y_deja_sin_arribos_al_final():
    evento = {
        "event_time": "2026-10-28 15:23:36",
        "latitude": -52.857,
        "longitude": -71.57,
    }
    arribos = [
        {
            "red": "C1",
            "estacion": "MG04",
            "fase": "P",
            "llegada": "2026-10-28 15:27:41.921878",
            "lat": -52.857232,
            "lon": -71.569992,
            "distancia": 0.0258,
        },
        {
            "red": "C1",
            "estacion": "MG03",
            "fase": "P",
            "llegada": "2026-10-28 15:27:41.512964",
            "lat": -51.67,
            "lon": -71.57,
            "distancia": 132.4,
        },
    ]
    sin_arribos = [
        {
            "red": "C1",
            "estacion": "ZZZ",
            "lat": -50.0,
            "lon": -70.0,
            "distancia_num": 300.0,
            "_categoria": "normal",
            "evidencia": "",
            "formas_onda": "",
            "streams_ids": "",
            "disponible": "",
        }
    ]

    datos = _datos_mapa_tiempos(evento, arribos, sin_arribos)

    assert [punto["estacion"] for punto in datos["estaciones_mapa"]] == [
        "MG03",
        "MG04",
        "ZZZ",
    ]
    assert datos["estaciones_mapa"][0]["tipo"] == "arribo"
    assert datos["estaciones_mapa"][-1]["tipo"] == "sin_arribo"
