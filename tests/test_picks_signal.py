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


def test_candidatos_prioriza_verticales_de_mayor_frecuencia():
    evento = _evento()
    detalle = [
        {
            "tipo": "sin_picar",
            "network": "C",
            "station": "GO02",
            "location": "",
            "channel": "LHZ",
            "distance_km": 22.2,
            "streams": ["C.GO02..LHZ", "C.GO02..BHZ"],
        }
    ]
    picks = picks_signal._picks_evento(evento, _tres_picks())
    intercepto, pendiente = picks_signal._ajuste(evento, picks)
    candidatos = picks_signal._candidatos(
        evento, detalle, intercepto, pendiente, 10
    )
    assert [item["stream"] for item in candidatos] == [
        "C.GO02..BHZ",
        "C.GO02..LHZ",
    ]


def test_analizar_evento_usa_el_vertical_con_datos():
    evento = _evento()
    detalle = [
        {
            "tipo": "sin_picar",
            "network": "C",
            "station": "GO02",
            "location": "",
            "channel": "LHZ",
            "distance_km": 22.2,
            "streams": ["C.GO02..LHZ", "C.GO02..BHZ"],
        }
    ]

    def falso(payload):
        resultados = []
        for candidato in payload["candidates"]:
            con_datos = candidato["stream"].endswith("BHZ")
            resultados.append(
                {
                    "stream": candidato["stream"],
                    "station": candidato["station"],
                    "status": "CON_DATOS" if con_datos else "SIN_DATOS",
                    "clasificacion": (
                        "senal_detectada" if con_datos else "sin_datos"
                    ),
                    "sta_lta_racha_s": 1.0 if con_datos else 0.0,
                }
            )
        return {"resultados": resultados}

    resultado = picks_signal.analizar_evento(
        evento,
        detalle,
        _tres_picks(),
        correlacionar_fn=falso,
    )
    assert resultado["senal_estado"] == "analizado"
    assert resultado["senal_n"] == 1
    assert "C.GO02" in resultado["senal_estaciones"]


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
        [
            *_tres_picks(),
            _arribo("R3", -30.3, segundos=12, usada=False, fase="S"),
        ],
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


def test_huella_cambia_con_el_evento_y_las_candidatas():
    fila = {
        "evento": "seiscomp:000001",
        "fecha_hora": "2026-01-01 00:00:00",
        "latitud": -30.0,
        "longitud": -71.0,
        "profundidad_km": 30.0,
        "magnitud": 4.0,
        "detalle": _detalle_candidata(),
    }
    base = picks_signal.huella_fila(fila)

    otra_candidata = json.loads(json.dumps(fila))
    otra_candidata["detalle"][0]["distance_km"] = 99.0
    assert picks_signal.huella_fila(otra_candidata) != base

    otro_evento = json.loads(json.dumps(fila))
    otro_evento["fecha_hora"] = "2026-01-01 00:00:01"
    assert picks_signal.huella_fila(otro_evento) != base


def test_guardar_resultado_y_completar_reporte(app, tmp_path):
    workspace = _preparar_reporte(tmp_path)
    fila = picks_coverage.leer(workspace, "seiscomp")[0]
    resultado = {
        "senal_n": 2,
        "senal_estaciones": "C1.CAND (1-5,1-10)",
        "senal_estado": "analizado",
        "detalle": {"candidatas": 1, "claras": {"C1.CAND": ["1-5", "1-10"]}},
    }
    assert picks_signal.guardar_resultado("seiscomp", fila, resultado)

    antes = picks_coverage.leer(workspace, "seiscomp")[0]
    assert antes["senal_estado"] == "pendiente"

    assert picks_signal.completar_reporte(workspace, "seiscomp") == 1
    despues = picks_coverage.leer(workspace, "seiscomp")[0]
    assert despues["senal_estado"] == "analizado"
    assert int(despues["senal_n"]) == 2
    assert "C1.CAND" in despues["senal_estaciones"]


def test_importar_reporte_preserva_el_resultado_tras_regenerar(app, tmp_path):
    workspace = _preparar_reporte(tmp_path)
    picks_coverage.actualizar_senal(
        workspace,
        "seiscomp",
        "seiscomp:000001",
        senal_n=2,
        senal_estaciones="C1.CAND (1-5,1-10)",
        senal_estado="analizado",
    )
    assert picks_signal.importar_reporte(workspace, "seiscomp") == 1

    picks_coverage.generar(workspace, "seiscomp")
    regenerado = picks_coverage.leer(workspace, "seiscomp")[0]
    assert regenerado["senal_estado"] == "pendiente"

    assert picks_signal.completar_reporte(workspace, "seiscomp") == 1
    restaurado = picks_coverage.leer(workspace, "seiscomp")[0]
    assert restaurado["senal_estado"] == "analizado"
    assert int(restaurado["senal_n"]) == 2


def test_mapa_resultados_ignora_una_huella_obsoleta(app, tmp_path):
    workspace = _preparar_reporte(tmp_path)
    fila = picks_coverage.leer(workspace, "seiscomp")[0]
    picks_signal.guardar_resultado(
        "seiscomp",
        fila,
        {
            "senal_n": 1,
            "senal_estaciones": "C1.CAND (1-5,1-10)",
            "senal_estado": "analizado",
            "detalle": {},
        },
    )
    assert picks_signal.mapa_resultados("seiscomp", [fila])

    obsoleta = json.loads(json.dumps(fila))
    obsoleta["detalle"][0]["distance_km"] = 99.0
    assert picks_signal.mapa_resultados("seiscomp", [obsoleta]) == {}


def test_combinar_picks_usa_resultado_persistente(app, tmp_path):
    from app.blueprints.results import _combinar_picks

    workspace = _preparar_reporte(tmp_path)
    fila = picks_coverage.leer(workspace, "seiscomp")[0]
    picks_signal.guardar_resultado(
        "seiscomp",
        fila,
        {
            "senal_n": 2,
            "senal_estaciones": "C1.CAND (1-5,1-10)",
            "senal_estado": "analizado",
            "detalle": {},
        },
    )

    filas: list[dict] = []
    _combinar_picks(filas, workspace, "seiscomp")
    assert filas[0]["picks_senal_estado"] == "analizado"
    assert filas[0]["picks_senal_n"] == 2


def test_guardar_resultado_actualiza_el_mismo_registro(app, tmp_path):
    from sqlalchemy import select

    from app.extensions import db
    from app.models import PicksSignalResult

    workspace = _preparar_reporte(tmp_path)
    fila = picks_coverage.leer(workspace, "seiscomp")[0]
    for senal_n in (1, 3):
        assert picks_signal.guardar_resultado(
            "seiscomp",
            fila,
            {
                "senal_n": senal_n,
                "senal_estaciones": "C1.CAND (1-5,1-10)",
                "senal_estado": "analizado",
                "detalle": {},
            },
        )
    resultados = db.session.scalars(
        select(PicksSignalResult).where(
            PicksSignalResult.event_id == "seiscomp:000001"
        )
    ).all()
    assert len(resultados) == 1
    assert resultados[0].senal_n == 3


def test_anotar_senal_en_el_detalle(app, tmp_path):
    from app.blueprints.results import _anotar_senal

    workspace = _preparar_reporte(tmp_path)
    fila = picks_coverage.leer(workspace, "seiscomp")[0]
    picks_signal.guardar_resultado(
        "seiscomp",
        fila,
        {
            "senal_n": 1,
            "senal_estaciones": "C1.CAND (1-5,1-10)",
            "senal_estado": "analizado",
            "detalle": {
                "candidatas": 2,
                "candidatas_labels": ["C1.CAND", "C1.OTHER"],
                "claras": {"C1.CAND": ["1-5", "1-10"]},
            },
        },
    )
    revision = {
        "fuente": "seiscomp",
        "evento": {"event_id": "seiscomp:000001"},
        "sin_arribos": [
            {"red": "C1", "estacion": "CAND"},
            {"red": "C1", "estacion": "OTHER"},
        ],
        "columnas_sin_arribos": [("formas_onda", "Formas de onda")],
    }
    _anotar_senal(workspace, revision)

    assert revision["senal"]["n"] == 1
    assert [item["texto"] for item in revision["senal"]["fases_no_usadas"]] == [
        "C1.R3 S"
    ]
    assert revision["sin_arribos"][0]["senal"].startswith("Clara")
    assert revision["sin_arribos"][1]["senal"] == "Sin señal clara"
    assert ("senal", "Señal") in revision["columnas_sin_arribos"]


def test_analizar_guarda_el_resultado_en_la_base(app, tmp_path):
    from sqlalchemy import select

    from app.extensions import db
    from app.models import PicksSignalResult

    workspace = _preparar_reporte(tmp_path)
    resultado = picks_signal.analizar(
        workspace,
        "seiscomp",
        correlacionar_fn=lambda payload: _respuesta("CAND"),
    )
    assert resultado["eventos"] == 1
    guardados = db.session.scalars(
        select(PicksSignalResult).where(
            PicksSignalResult.event_id == "seiscomp:000001"
        )
    ).all()
    assert len(guardados) == 1
    assert guardados[0].estado == "analizado"
    assert guardados[0].senal_n == 1


def test_analizar_informa_el_progreso(tmp_path):
    workspace = _preparar_reporte(tmp_path)
    avances = []
    picks_signal.analizar(
        workspace,
        "seiscomp",
        correlacionar_fn=lambda payload: _respuesta("CAND"),
        progreso=lambda indice, total, evento: avances.append(
            (indice, total, evento)
        ),
    )
    assert avances == [(1, 1, "seiscomp:000001")]


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
