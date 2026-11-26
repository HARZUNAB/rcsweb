"""Pruebas de la confirmación de señal de estaciones sin aportar."""

from __future__ import annotations

import json
from pathlib import Path

from app.domain.catalogs import canonical
from app.services import availability, picks_coverage, picks_signal


def _evento(event_id: str = "seiscomp:000001") -> dict:
    return {
        "source_id": "seiscomp",
        "event_id": event_id,
        "source_event_id": f"src-{event_id}",
        "event_time": "2026-01-01 00:00:00",
        "latitude": -30.0,
        "longitude": -71.0,
        "depth_km": 30.0,
        "magnitude": 4.0,
        "analyst": "ana",
        "raw_index": 0,
        "origin_quality": {"used_station_count": 3},
    }


def _arribo(
    station: str,
    lat: float,
    *,
    segundos: int,
    usada: bool = True,
    fase: str = "P",
) -> dict:
    hora = f"2026-01-01 00:00:{segundos:02d}"
    return {
        "source_id": "seiscomp",
        "event_id": "seiscomp:000001",
        "network": "C1",
        "station": station,
        "location": "",
        "channel": "HNZ",
        "phase": fase,
        "pick_time": hora,
        "is_used_in_solution": usada,
        "weight": 1.0 if usada else 0.0,
        "station_latitude": lat,
        "station_longitude": -71.0,
    }


def _detalle_candidata(
    station: str = "CAND",
    *,
    distancia: float = 80.0,
) -> list[dict]:
    return [
        {
            "tipo": "sin_picar",
            "network": "C1",
            "station": station,
            "location": "",
            "channel": "HNZ",
            "distance_km": distancia,
            "streams": [f"C1.{station}..HNZ"],
        }
    ]


def _respuesta(
    station: str,
    *,
    clasificacion: str = "senal_detectada",
    racha: float = 1.0,
    status: str = "CON_DATOS",
) -> dict:
    return {
        "resultados": [
            {
                "stream": f"C1.{station}..HNZ",
                "station": f"AVAIL C1.{station}..HNZ",
                "status": status,
                "clasificacion": clasificacion,
                "sta_lta_racha_s": racha,
            }
        ]
    }


def _tres_picks() -> list[dict]:
    return [
        _arribo("R1", -30.1, segundos=5),
        _arribo("R2", -30.2, segundos=8),
        _arribo("R3", -30.3, segundos=11),
    ]


def test_analizar_evento_exige_dos_bandas():
    respuesta = picks_signal.analizar_evento(
        _evento(),
        _detalle_candidata(),
        _tres_picks(),
        correlacionar_fn=lambda payload: _respuesta(
            "CAND",
            clasificacion=(
                "senal_detectada"
                if payload["band"] in ([1.0, 5.0], [1.0, 10.0])
                else "sin_senal"
            ),
            racha=1.0 if payload["band"] != [2.0, 15.0] else 0.1,
        ),
    )
    assert respuesta["senal_estado"] == "analizado"
    assert respuesta["senal_n"] == 1
    assert "C1.CAND" in respuesta["senal_estaciones"]


def test_analizar_evento_una_banda_no_confirma():
    respuesta = picks_signal.analizar_evento(
        _evento(),
        _detalle_candidata(),
        _tres_picks(),
        correlacionar_fn=lambda payload: _respuesta(
            "CAND",
            clasificacion=(
                "senal_detectada"
                if payload["band"] == [1.0, 5.0]
                else "sin_senal"
            ),
        ),
    )
    assert respuesta["senal_estado"] == "analizado"
    assert respuesta["senal_n"] == 0


def test_analizar_evento_sin_datos():
    respuesta = picks_signal.analizar_evento(
        _evento(),
        _detalle_candidata(),
        _tres_picks(),
        correlacionar_fn=lambda payload: _respuesta(
            "CAND", status="SIN_DATOS", clasificacion="sin_datos", racha=0.0
        ),
    )
    assert respuesta["senal_estado"] == "sin_datos"
    assert respuesta["senal_n"] == 0


def test_analizar_evento_sin_arribos_es_sin_datos():
    respuesta = picks_signal.analizar_evento(
        _evento(),
        _detalle_candidata(),
        [],
        correlacionar_fn=lambda payload: _respuesta("CAND"),
    )
    assert respuesta["senal_estado"] == "sin_datos"


def _preparar_reporte(tmp_path: Path) -> Path:
    workspace = tmp_path / "ws"
    canonical.escribir_registros(
        canonical.ruta_canonica(workspace, "seiscomp"),
        [_evento()],
    )
    canonical.escribir_registros(
        canonical.ruta_arribos(workspace, "seiscomp"),
        _tres_picks(),
    )
    canonical.escribir_registros(
        canonical.ruta_estaciones_sin_arribos(workspace, "seiscomp"),
        [
            {
                "source_id": "seiscomp",
                "event_id": "seiscomp:000001",
                "network": "C1",
                "station": "CAND",
                "location": "",
                "channel": "HNZ",
                "streams": "C1.CAND..HNZ",
                "stream_ids": "C1.CAND..HNZ",
                "station_latitude": -30.4,
                "station_longitude": -71.0,
                "evidence": "NO_CONSULTADO",
                "waveform_status": "NO_CONSULTADO",
            }
        ],
    )
    picks_coverage.generar(workspace, "seiscomp")
    return workspace


def test_analizar_actualiza_el_reporte(tmp_path):
    workspace = _preparar_reporte(tmp_path)
    resultado = picks_signal.analizar(
        workspace,
        "seiscomp",
        correlacionar_fn=lambda payload: _respuesta("CAND"),
    )
    assert resultado["eventos"] == 1
    assert resultado["con_senal"] == 1
    filas = picks_coverage.leer(workspace, "seiscomp")
    assert filas[0]["senal_estado"] == "analizado"
    assert int(filas[0]["senal_n"]) == 1
    assert "C1.CAND" in filas[0]["senal_estaciones"]
    assert filas[0]["senal_actualizado"]


def test_analizar_omite_eventos_ya_analizados(tmp_path):
    workspace = _preparar_reporte(tmp_path)
    picks_coverage.actualizar_senal(
        workspace,
        "seiscomp",
        "seiscomp:000001",
        senal_n=1,
        senal_estaciones="C1.OTRA",
        senal_estado="analizado",
    )
    llamadas = []
    resultado = picks_signal.analizar(
        workspace,
        "seiscomp",
        correlacionar_fn=lambda payload: (
            llamadas.append(payload) or _respuesta("CAND")
        ),
    )
    assert resultado["eventos"] == 0
    assert llamadas == []


def test_analizar_respeta_max_eventos(tmp_path):
    workspace = _preparar_reporte(tmp_path)
    filas = picks_coverage.leer(workspace, "seiscomp")
    assert len(filas) == 1
    resultado = picks_signal.analizar(
        workspace,
        "seiscomp",
        max_eventos=0,
        correlacionar_fn=lambda payload: _respuesta("CAND"),
    )
    assert resultado["eventos"] == 0


def test_analizar_no_marca_evento_si_falla_el_servicio(tmp_path):
    workspace = _preparar_reporte(tmp_path)

    def falla(_payload):
        raise availability.AvailabilityError("servicio no disponible")

    resultado = picks_signal.analizar(
        workspace, "seiscomp", correlacionar_fn=falla
    )
    assert resultado["eventos"] == 0
    assert resultado["errores"] == 1
    filas = picks_coverage.leer(workspace, "seiscomp")
    assert filas[0]["senal_estado"] == "pendiente"


def test_payload_incluye_tiempo_esperado_por_distancia_hipocentral(tmp_path):
    workspace = _preparar_reporte(tmp_path)
    capturado = {}

    def falso(payload):
        capturado.update(payload)
        return _respuesta("CAND")

    picks_signal.analizar(workspace, "seiscomp", correlacionar_fn=falso)
    candidata = capturado["candidates"][0]
    assert candidata["station"] == "AVAIL C1.CAND..HNZ"
    assert candidata["expected_time"]
    assert json.loads(json.dumps(capturado)) == capturado
