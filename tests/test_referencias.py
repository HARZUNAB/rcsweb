"""Pruebas de la resolución de referencias Eventquery a soluciones locales."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta

from app.domain.catalogs import canonical
from app.services import referencias

EVENT_TIME = "2026-11-06 07:23:35"


def _workspace(tmp_path):
    workspace = tmp_path / "ws"
    (workspace / "catalogo" / "seiscomp").mkdir(parents=True)
    (workspace / "datos").mkdir(parents=True)
    evento = {
        "source_id": "seiscomp",
        "event_id": "seiscomp:000584",
        "event_time": EVENT_TIME,
        "latitude": -28.359,
        "longitude": -71.875,
        "depth_km": 46.5,
        "magnitude": 3.6,
        "magnitude_type": "MLv",
        "analyst": "maca",
        "raw_index": 0,
        "raw": {},
    }
    canonical.escribir_registros(
        canonical.ruta_canonica(workspace, "seiscomp"), [evento]
    )
    base = datetime.fromisoformat(EVENT_TIME)
    arribos = []
    for indice, (tp, ts) in enumerate(
        [(5.0, 8.75), (10.0, 17.5), (15.0, 26.25), (20.0, 35.0)],
        start=1,
    ):
        estacion = f"E{indice}"
        for fase, segundos in (("P", tp), ("S", ts)):
            arribos.append(
                {
                    "source_id": "seiscomp",
                    "event_id": "seiscomp:000584",
                    "network": "C1",
                    "station": estacion,
                    "phase": fase,
                    "pick_time": (base + timedelta(seconds=segundos)).isoformat(
                        sep=" "
                    ),
                    "residual": 0.0,
                    "weight": 0.0,
                    "is_used_in_solution": True,
                    "station_latitude": -28.0 - indice * 0.1,
                    "station_longitude": -71.8,
                    "azimuth": indice * 45.0,
                    "distance_km": 10.0 * indice,
                    "raw": {},
                }
            )
    canonical.escribir_registros(
        canonical.ruta_arribos(workspace, "seiscomp"), arribos
    )
    return workspace


def _atribucion(workspace, **cambios):
    fila = {
        "n_fila_eventquery": "0",
        "fecha_eventquery": EVENT_TIME,
        "lat_eventquery": "-28.359",
        "lon_eventquery": "-71.875",
        "prof_eventquery": "46.5",
        "mag_eventquery": "3.6",
        "tipo_mag_eventquery": "MLv",
        "percibido": "N",
        "fecha_local": EVENT_TIME,
        "lat_local": "-28.359",
        "lon_local": "-71.875",
        "prof_local": "46.5",
        "mag_local": "3.6",
        "tipo_mag_local": "MLv",
        "analista": "maca",
        "dt_seg": "0.0",
        "dlat": "0.0",
        "dlon": "0.0",
        "dist_km": "0.1",
        "n_candidatos": "1",
        "fuente": "seiscomp",
    }
    fila.update(cambios)
    ruta = workspace / "datos" / "atribucion_seiscomp.csv"
    with ruta.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=list(fila))
        escritor.writeheader()
        escritor.writerow(fila)
    return ruta


def test_resuelve_solucion_local_y_wadati(tmp_path):
    workspace = _workspace(tmp_path)
    _atribucion(workspace)

    candidatos = referencias.soluciones_locales(
        workspace, 0, "SeisComp: maca"
    )

    assert len(candidatos) == 1
    candidato = candidatos[0]
    assert candidato["fuente"] == "seiscomp"
    assert candidato["evento_local"] == "seiscomp:000584"
    assert candidato["fila_local"] == 0
    assert candidato["probable"] is True
    assert candidato["wadati"]["n_pares"] == 4
    assert abs(candidato["wadati"]["vp_vs"] - 1.75) < 1e-6
    assert candidato["wadati"]["calidad"] == "consistente"


def test_fuente_no_probable(tmp_path):
    workspace = _workspace(tmp_path)
    _atribucion(workspace)

    candidatos = referencias.soluciones_locales(
        workspace, 0, "Seisan: otro"
    )

    assert len(candidatos) == 1
    assert candidatos[0]["probable"] is False


def test_referencia_sin_atribucion_devuelve_vacio(tmp_path):
    workspace = _workspace(tmp_path)
    _atribucion(workspace)

    assert referencias.soluciones_locales(workspace, 99) == []


def test_evento_local_no_encontrado_sigue_siendo_candidato(tmp_path):
    workspace = _workspace(tmp_path)
    _atribucion(workspace, fecha_local="2026-11-06 07:23:00")

    candidatos = referencias.soluciones_locales(workspace, 0)

    assert len(candidatos) == 1
    assert candidatos[0]["evento_local"] == ""
    assert candidatos[0]["fila_local"] is None
    assert candidatos[0]["wadati"]["calidad"] == "insuficiente"
