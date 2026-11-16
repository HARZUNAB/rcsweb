"""Pruebas del cruce de no publicados contra todas las fuentes locales."""

from __future__ import annotations

import csv

from app.domain.catalogs import canonical
from app.services import no_publicados


def _evento(source_id: str, event_id: str, *, hora: str, lat: float, lon: float):
    return {
        "source_id": source_id,
        "event_id": event_id,
        "source_event_id": event_id,
        "event_time": hora,
        "latitude": lat,
        "longitude": lon,
        "depth_km": 10.0,
        "magnitude": 3.0,
        "magnitude_type": "ML",
        "analyst": "analista",
        "raw_index": 0,
        "raw": {},
    }


def _escribir_atribucion(workspace, source_id, hora, lat, lon):
    ruta = workspace / "datos" / f"atribucion_{source_id}.csv"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.DictWriter(
            archivo, fieldnames=["fecha_local", "lat_local", "lon_local"]
        )
        escritor.writeheader()
        escritor.writerow(
            {"fecha_local": hora, "lat_local": lat, "lon_local": lon}
        )


def test_no_publicado_encuentra_varias_fuentes_y_su_cruce(tmp_path):
    workspace = tmp_path / "ws"
    canonical.escribir_registros(
        canonical.ruta_canonica(workspace, "seiscomp"),
        [
            _evento(
                "seiscomp",
                "seiscomp:000001",
                hora="2026-11-09 11:45:39",
                lat=-41.80,
                lon=-75.90,
            ),
            _evento(
                "seiscomp",
                "seiscomp:000002",
                hora="2026-11-09 12:00:00",
                lat=-30.0,
                lon=-71.0,
            ),
        ],
    )
    _escribir_atribucion(
        workspace, "seiscomp", "2026-11-09 11:45:39", -41.80, -75.90
    )

    fila = {
        "Fecha_Hora": "2026-11-09  11:45:35",
        "Latitud": "-41.809",
        "Longitud": "-75.917",
    }
    resultado = no_publicados.coincidencias(
        workspace, "seisan", fila, ["seiscomp", "central"]
    )

    fuentes = {item["fuente"]: item for item in resultado["fuentes"]}
    assert fuentes["seiscomp"]["existe"] is True
    assert fuentes["seiscomp"]["estado"] == "con_cruce"
    assert fuentes["seiscomp"]["n_candidatos"] == 1
    assert fuentes["central"]["existe"] is False
    assert resultado["fuentes_con_cruce"] == ["SeisComp"]
    assert resultado["estado"] == "con_cruce"


def test_no_publicado_puede_existir_sin_cruce(tmp_path):
    workspace = tmp_path / "ws"
    canonical.escribir_registros(
        canonical.ruta_canonica(workspace, "seiscomp"),
        [
            _evento(
                "seiscomp",
                "seiscomp:000003",
                hora="2026-11-10 08:00:00",
                lat=-35.0,
                lon=-72.0,
            )
        ],
    )

    fila = {
        "Fecha_Hora": "2026-11-10 08:00:02",
        "Latitud": "-35.001",
        "Longitud": "-72.001",
    }
    resultado = no_publicados.coincidencias(
        workspace, "seisan", fila, ["seiscomp"]
    )

    item = resultado["fuentes"][0]
    assert item["existe"] is True
    assert item["estado"] == "sin_evaluar"
    assert resultado["fuentes_con_evento"] == ["SeisComp"]
    assert resultado["fuentes_con_cruce"] == []
    assert resultado["estado"] == "sin_cruce"
