"""Pruebas de los indicios de anomalías en la identificación de fases."""

from __future__ import annotations

import csv
from pathlib import Path

from app.domain.catalogs import canonical
from app.services import indicios


def _evento(**cambios) -> dict:
    base = {
        "source_id": "seiscomp",
        "event_id": "seiscomp:000001",
        "source_event_id": "csn_sc62026vdkls",
        "event_time": "2026-10-28 15:23:36",
        "latitude": -52.857,
        "longitude": -71.570,
        "depth_km": 10.0,
        "magnitude": None,
        "analyst": "mdur",
        "raw_index": 2650,
        "raw": {},
    }
    base.update(cambios)
    return base


def _arribo(
    estacion: str,
    lat: float,
    lon: float,
    pick: str,
    residual: float,
    *,
    weight: float = 1.0,
    phase: str = "P",
    usada: bool = True,
    azimuth: float | None = None,
    raw: dict | None = None,
) -> dict:
    return {
        "source_id": "seiscomp",
        "event_id": "seiscomp:000001",
        "network": "C1",
        "station": estacion,
        "phase": phase,
        "pick_time": pick,
        "residual": residual,
        "weight": weight,
        "is_used_in_solution": usada,
        "azimuth": azimuth,
        "distance_km": None,
        "station_latitude": lat,
        "station_longitude": lon,
        "raw": raw or {},
    }


def _caso_mg04() -> list[dict]:
    return [
        _arribo("MG04", -52.857232, -71.569992, "2026-10-28 15:27:41.921878", 244.200065),
        _arribo("MG03", -51.670000, -71.570000, "2026-10-28 15:27:41.512964", 223.471888),
        _arribo("MG02", -51.430000, -71.570000, "2026-10-28 15:27:44.457146", 222.982285),
        _arribo("USHA", -50.150000, -71.570000, "2026-10-28 15:27:43.230404", 203.630270),
        _arribo("AY05", -45.000000, -71.570000, "2026-10-28 15:27:42.576141", 132.892849),
    ]


def _escribir(workspace: Path, source_id: str, eventos, arribos, sin_arribos=()) -> None:
    canonical.escribir_registros(
        canonical.ruta_canonica(workspace, source_id), eventos
    )
    canonical.escribir_registros(
        canonical.ruta_arribos(workspace, source_id), arribos
    )
    if sin_arribos:
        canonical.escribir_registros(
            canonical.ruta_estaciones_sin_arribos(workspace, source_id),
            sin_arribos,
        )


def test_detecta_caso_puntual_extremo_y_lo_marca_prioritario():
    resultado = indicios.evaluar_evento(
        _evento(),
        _caso_mg04(),
        source_id="seiscomp",
        publicado=True,
    )

    assert resultado["anomalia"] is True
    assert resultado["fuerza"] == "fuerte"
    assert resultado["patron"] == "puntual"
    assert resultado["contexto"] == "débil"
    assert resultado["extremo"] is True
    assert resultado["n_outliers"] == 5
    assert resultado["n_inversiones"] > 0
    assert resultado["revision_prioritaria"] is True
    assert resultado["max_residual_usado"] == "244.20"
    assert resultado["evidencia"]


def test_no_alarma_si_el_evento_no_esta_publicado():
    resultado = indicios.evaluar_evento(
        _evento(),
        _caso_mg04(),
        source_id="seiscomp",
        publicado=False,
    )

    assert resultado["anomalia"] is True
    assert resultado["revision_prioritaria"] is False
    assert resultado["publicado"] is False


def test_patron_sistematico_con_contexto_fuerte():
    evento = _evento(
        event_id="seiscomp:000002",
        event_time="2020-01-01 00:00:00",
        latitude=0.0,
        longitude=0.0,
        source_event_id="ev-2",
    )
    arribos = [
        _arribo("A", 0.5, 0.0, "2020-01-01 00:00:10", 6.0, azimuth=0),
        _arribo("B", 0.4, 0.4, "2020-01-01 00:00:12", 7.0, azimuth=60),
        _arribo("C", 0.0, 0.5, "2020-01-01 00:00:14", 8.0, azimuth=120),
        _arribo("D", -0.5, 0.0, "2020-01-01 00:00:16", 6.5, azimuth=180),
        _arribo("E", -0.4, -0.4, "2020-01-01 00:00:18", 7.5, azimuth=240),
        _arribo("F", 0.0, -0.5, "2020-01-01 00:00:20", 8.5, azimuth=300),
    ]
    sin_arribos = [
        {"event_id": "seiscomp:000002", "network": "C1", "station": "G"},
        {"event_id": "seiscomp:000002", "network": "C1", "station": "H"},
    ]
    resultado = indicios.evaluar_evento(
        evento,
        arribos,
        sin_arribos,
        source_id="seiscomp",
        publicado=True,
        perfil_disponible=True,
    )

    assert resultado["fuerza"] == "fuerte"
    assert resultado["patron"] == "sistemático"
    assert resultado["contexto"] == "fuerte"
    assert resultado["extremo"] is False
    assert resultado["revision_prioritaria"] is True


def test_detecta_pick_antes_del_origen():
    evento = _evento(
        event_id="seiscomp:000003",
        event_time="2020-01-01 00:00:00",
        latitude=0.0,
        longitude=0.0,
    )
    arribos = [
        _arribo("A", 0.5, 0.0, "2019-12-31 23:59:55", -10.0),
    ]
    resultado = indicios.evaluar_evento(
        evento, arribos, source_id="seiscomp", publicado=True
    )

    assert resultado["anomalia"] is True
    assert resultado["fuerza"] == "fuerte"
    assert resultado["patron"] == "pick_antes_origen"
    assert resultado["n_picks_antes_origen"] == 1


def test_peso_bajo_no_genera_indicio():
    evento = _evento(
        event_id="seiscomp:000004",
        event_time="2020-01-01 00:00:00",
        latitude=0.0,
        longitude=0.0,
    )
    arribos = [
        _arribo("A", 0.1, 0.0, "2020-01-01 00:00:05", 100.0, weight=0.1),
    ]
    resultado = indicios.evaluar_evento(
        evento, arribos, source_id="seiscomp", publicado=True
    )

    assert resultado["anomalia"] is False
    assert resultado["fuerza"] == ""
    assert resultado["revision_prioritaria"] is False
    assert resultado["n_outliers"] == 0


def test_detecta_inversion_debil_con_peso_casi_nulo():
    evento = _evento(
        event_id="seiscomp:000006",
        event_time="2020-01-01 00:00:00",
        latitude=0.0,
        longitude=0.0,
    )
    arribos = [
        _arribo("TOQ0", 0.4, 0.0, "2020-01-01 00:00:06", -0.1, weight=1.4),
        _arribo(
            "AP01",
            1.3,
            0.0,
            "2020-01-01 00:00:20",
            7.27,
            weight=3.6e-22,
            raw={"peso": 3.6e-22},
        ),
        _arribo("PB12", 1.5, 0.0, "2020-01-01 00:00:16", 0.32, weight=1.37),
    ]
    resultado = indicios.evaluar_evento(
        evento, arribos, source_id="seiscomp", publicado=True
    )

    assert resultado["anomalia"] is True
    assert resultado["fuerza"] == "débil"
    assert resultado["patron"] == "inversion_debil"
    assert resultado["n_inversiones_debiles"] == 1
    assert resultado["n_inversiones"] == 0
    assert resultado["revision_prioritaria"] is False
    assert resultado["resumen"] == "inversion_debil | residual +7.27 s | peso 4"
    debil = next(
        item
        for item in resultado["evidencia"]
        if item["tipo_indicio"] == "inversion_debil"
    )
    assert debil["peso"] == "4"
    assert debil["peso_original"] == "3.6e-22"
    assert debil["t_seg"] == "20.0"
    assert debil["residual"] == "+7.27"


def test_marca_residual_temporal_desde_la_procedencia():
    arribos = [
        _arribo(
            "A",
            0.1,
            0.0,
            "2020-01-01 00:00:05",
            100.0,
            raw={"residual_fuente": "seisan", "residual_temporal": True},
        )
    ]
    resultado = indicios.evaluar_evento(
        _evento(event_id="seiscomp:000005"), arribos, source_id="seiscomp"
    )

    assert resultado["residual_temporal"] is True
    assert resultado["residual_fuentes"] == "seisan"


def test_genera_reportes_y_resumen(tmp_path):
    workspace = tmp_path / "ws"
    evento = _evento()
    _escribir(workspace, "seiscomp", [evento], _caso_mg04())
    atribucion = workspace / "datos" / "atribucion_seiscomp.csv"
    atribucion.parent.mkdir(parents=True)
    with atribucion.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.DictWriter(
            archivo, fieldnames=["fecha_local", "lat_local", "lon_local"]
        )
        escritor.writeheader()
        escritor.writerow(
            {
                "fecha_local": "2026-10-28 15:23:36",
                "lat_local": "-52.857",
                "lon_local": "-71.570",
            }
        )

    resumen = indicios.generar_indicios(workspace, ["seiscomp"], job_id="job-1")

    assert resumen["total"]["eventos"] == 1
    assert resumen["total"]["con_anomalia"] == 1
    assert resumen["total"]["con_anomalia_fuerte"] == 1
    assert resumen["total"]["con_anomalia_debil"] == 0
    assert resumen["total"]["revision_prioritaria"] == 1
    assert resumen["fuentes"]["seiscomp"]["publicados"] == 1

    filas = indicios.leer_indicios(workspace, "seiscomp")
    assert len(filas) == 1
    assert filas[0]["id_evento_fuente"] == "csn_sc62026vdkls"
    assert filas[0]["publicado"] == "Sí"
    assert filas[0]["revision_prioritaria"] == "Sí"
    assert filas[0]["fuerza"] == "fuerte"
    assert filas[0]["patron"] == "puntual"
    assert filas[0]["contexto"] == "débil"
    assert filas[0]["max_residual_usado"] == "244.20"
    assert filas[0]["resumen"].startswith("puntual | residual +244.20 s")

    detalle = indicios.leer_detalle(workspace, "seiscomp", "seiscomp:000001")
    assert detalle
    assert any(item["tipo_indicio"] == "residual_alto" for item in detalle)

    assert indicios.leer_resumen(workspace) == resumen


def test_estado_publicado_sin_atribucion_es_desconocido(tmp_path):
    workspace = tmp_path / "ws"
    assert (
        indicios.estado_publicado(workspace, "seiscomp", _evento())
        is None
    )
