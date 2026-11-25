"""Pruebas del reporte de estaciones cercanas sin aportar."""

from __future__ import annotations

from pathlib import Path

from app.domain.catalogs import canonical
from app.services import picks_coverage


def _evento(event_id: str, tiempo: str, lat: float, lon: float) -> dict:
    return {
        "source_id": "seiscomp",
        "event_id": event_id,
        "source_event_id": f"src-{event_id}",
        "event_time": tiempo,
        "latitude": lat,
        "longitude": lon,
        "depth_km": 30.0,
        "magnitude": 4.0,
        "magnitude_type": "MLv",
        "analyst": "ana",
        "raw_index": 0,
        "origin_quality": {"used_station_count": 2},
    }


def _arribo(
    event_id: str,
    station: str,
    lat: float,
    lon: float,
    *,
    usada: bool,
    fase: str = "P",
) -> dict:
    return {
        "source_id": "seiscomp",
        "event_id": event_id,
        "network": "C1",
        "station": station,
        "location": "",
        "channel": "HNZ",
        "phase": fase,
        "pick_time": "2026-01-01 00:00:10",
        "is_used_in_solution": usada,
        "weight": 1.0 if usada else 0.0,
        "station_latitude": lat,
        "station_longitude": lon,
    }


def _sin_arribo(
    event_id: str,
    station: str,
    lat: float,
    lon: float,
    *,
    streams: str = "C1.XXX..HNZ",
    evidence: str = "NO_CONSULTADO",
    waveform_status: str = "NO_CONSULTADO",
) -> dict:
    return {
        "source_id": "seiscomp",
        "event_id": event_id,
        "network": "C1",
        "station": station,
        "location": "",
        "channel": "HNZ",
        "streams": streams,
        "stream_ids": streams,
        "station_latitude": lat,
        "station_longitude": lon,
        "evidence": evidence,
        "waveform_status": waveform_status,
    }


def _preparar(tmp_path: Path) -> Path:
    workspace = tmp_path / "ws"
    canonical.escribir_registros(
        canonical.ruta_canonica(workspace, "seiscomp"),
        [
            _evento("seiscomp:000001", "2026-01-01 00:00:00", -30.0, -71.0),
            _evento("seiscomp:000002", "2026-01-02 00:00:00", -20.0, -69.0),
        ],
    )
    canonical.escribir_registros(
        canonical.ruta_arribos(workspace, "seiscomp"),
        [
            _arribo("seiscomp:000001", "USED1", -30.1, -71.0, usada=True),
            _arribo("seiscomp:000001", "USED2", -30.2, -71.0, usada=True),
            _arribo("seiscomp:000001", "UNUSED", -30.3, -71.0, usada=False),
        ],
    )
    canonical.escribir_registros(
        canonical.ruta_estaciones_sin_arribos(workspace, "seiscomp"),
        [
            _sin_arribo(
                "seiscomp:000001",
                "NEAR",
                -30.4,
                -71.0,
                streams="C1.NEAR..HNZ;C1.NEAR..HNN",
            ),
            _sin_arribo(
                "seiscomp:000001",
                "FAR",
                -35.0,
                -71.0,
            ),
            _sin_arribo(
                "seiscomp:000001",
                "NOVERT",
                -30.5,
                -71.0,
                streams="C1.NOVERT..HNN",
            ),
            _sin_arribo(
                "seiscomp:000001",
                "NO_EVID",
                -30.6,
                -71.0,
                evidence="SIN_EVIDENCIA",
            ),
            _sin_arribo(
                "seiscomp:000001",
                "NO_DATA",
                -30.7,
                -71.0,
                waveform_status="SIN_DATOS",
            ),
            _sin_arribo(
                "seiscomp:000001",
                "USED1",
                -30.1,
                -71.0,
            ),
        ],
    )
    return workspace


def test_generar_reporte_de_estaciones_sin_aportar(tmp_path):
    workspace = _preparar(tmp_path)
    resumen = picks_coverage.generar(
        workspace,
        "seiscomp",
        radio=250,
        cerca=100,
    )
    assert resumen["eventos"] == 1
    assert resumen["sin_picar"] == 1
    assert resumen["no_usadas"] == 1

    filas = picks_coverage.leer(workspace, "seiscomp")
    assert len(filas) == 1
    fila = filas[0]
    assert fila["evento"] == "seiscomp:000001"
    assert int(fila["sin_picar_n"]) == 1
    assert int(fila["no_usadas_n"]) == 1
    assert int(fila["total_n"]) == 2
    assert fila["prioridad"] == "Alta"
    assert "NEAR" in fila["estaciones"]
    assert "UNUSED" in fila["estaciones"]
    assert fila["senal_estado"] == "pendiente"
    tipos = {item["tipo"] for item in fila["detalle"]}
    assert tipos == {"sin_picar", "no_usada"}
    assert not any(
        item["station"]
        in {"FAR", "NOVERT", "NO_EVID", "NO_DATA", "USED1"}
        for item in fila["detalle"]
    )


def test_generar_respeta_radio_y_no_incluye_evento_sin_candidatas(tmp_path):
    workspace = _preparar(tmp_path)
    resumen = picks_coverage.generar(
        workspace,
        "seiscomp",
        radio=1,
        cerca=1,
    )
    assert resumen["eventos"] == 0
    assert picks_coverage.leer(workspace, "seiscomp") == []


def test_combinar_picks_agrega_fila_a_la_revision(tmp_path):
    from app.blueprints.results import _combinar_picks

    workspace = _preparar(tmp_path)
    picks_coverage.generar(workspace, "seiscomp")
    filas: list[dict] = []
    _combinar_picks(filas, workspace, "seiscomp")
    assert len(filas) == 1
    fila = filas[0]
    assert fila["evento"] == "seiscomp:000001"
    assert fila["motivo"] == "picks"
    assert fila["tipos_indicio"] == "picks_faltantes"
    assert fila["picks_total"] == 2
    assert fila["picks_prioridad"] == "Alta"
    assert fila["picks_orden"] == 5


def test_combinar_picks_conserva_fila_existente_y_suma_motivo(tmp_path):
    from app.blueprints.results import _combinar_picks

    workspace = _preparar(tmp_path)
    picks_coverage.generar(workspace, "seiscomp")
    filas = [
        {
            "evento": "seiscomp:000001",
            "motivo": "fase",
            "tipos_indicio": "residual_alto",
        }
    ]
    _combinar_picks(filas, workspace, "seiscomp")
    fila = filas[0]
    assert fila["motivo"] == "ambas"
    assert "picks_faltantes" in fila["tipos_indicio"]
    assert fila["picks_total"] == 2


def test_formato_del_tipo_picks_faltantes():
    from app.services import formatting

    assert (
        formatting.tipos_indicio_texto("picks_faltantes")
        == "Estaciones cercanas sin aportar"
    )
