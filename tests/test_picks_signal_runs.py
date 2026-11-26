"""Pruebas de las corridas persistentes de señal."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime

from app.extensions import db
from app.models import Job, PicksSignalRun, nuevo_uuid
from app.services import availability, picks_coverage, picks_signal_runs
from app.services.workspace import crear_workspace, ruta_workspace


def _job() -> Job:
    job = Job(
        id=nuevo_uuid(),
        status="done",
        period_start=datetime(2026, 1, 1, tzinfo=UTC),
        period_end=datetime(2026, 1, 31, tzinfo=UTC),
    )
    db.session.add(job)
    db.session.commit()
    crear_workspace(job.id)
    return job


def _reporte(job: Job, eventos=("seiscomp:A", "seiscomp:B")) -> None:
    destino = picks_coverage.ruta(ruta_workspace(job.id), "seiscomp")
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.DictWriter(
            archivo, fieldnames=picks_coverage.CAMPOS
        )
        escritor.writeheader()
        for event_id in eventos:
            escritor.writerow(
                {
                    "fuente": "seiscomp",
                    "evento": event_id,
                    "fecha_hora": "2026-01-01 00:00:00",
                    "latitud": -30.0,
                    "longitud": -71.0,
                    "profundidad_km": 30.0,
                    "magnitud": 4.0,
                    "n_usadas": 3,
                    "sin_picar_n": 1,
                    "no_usadas_n": 0,
                    "total_n": 1,
                    "prioridad": "Alta",
                    "detalle": json.dumps([]),
                    "senal_estado": "pendiente",
                }
            )


def _filas(eventos=("seiscomp:A", "seiscomp:B")) -> list[dict]:
    return [
        {"evento": event_id, "senal_pendiente": True}
        for event_id in eventos
    ]


def _preparar_analisis(monkeypatch, eventos=("seiscomp:A", "seiscomp:B")):
    monkeypatch.setattr(
        picks_signal_runs.canonical,
        "leer_canonico",
        lambda *_args, **_kwargs: [
            {"event_id": event_id} for event_id in eventos
        ],
    )
    monkeypatch.setattr(
        picks_signal_runs.canonical,
        "leer_arribos",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        picks_signal_runs.picks_signal,
        "analizar_evento",
        lambda *_args, **_kwargs: {
            "senal_n": 1,
            "senal_estaciones": "C1.CAND (1-5,1-10)",
            "senal_estado": "analizado",
            "detalle": {},
        },
    )


def test_crear_corrida_crea_items_en_orden(app):
    job = _job()
    run = picks_signal_runs.crear_corrida(
        job.id,
        "seiscomp",
        _filas(),
        alcance="todos",
    )
    assert run is not None
    assert run.total == 2
    assert run.status == "queued"
    items = db.session.get(PicksSignalRun, run.id).items
    assert [item.event_id for item in items] == [
        "seiscomp:A",
        "seiscomp:B",
    ]
    assert [item.position for item in items] == [1, 2]


def test_crear_corrida_omite_terminales_y_respeta_seleccion(app):
    job = _job()
    filas = [
        {"evento": "seiscomp:A", "senal_pendiente": True},
        {"evento": "seiscomp:B", "senal_pendiente": False},
        {"evento": "seiscomp:C", "senal_pendiente": True},
    ]
    run = picks_signal_runs.crear_corrida(
        job.id,
        "seiscomp",
        filas,
        evento_ids={"seiscomp:C"},
    )
    assert run.total == 1
    assert run.items[0].event_id == "seiscomp:C"


def test_procesar_lote_completa_y_guarda(app, monkeypatch):
    job = _job()
    _reporte(job)
    run = picks_signal_runs.crear_corrida(
        job.id, "seiscomp", _filas()
    )
    _preparar_analisis(monkeypatch)

    resultado = picks_signal_runs.procesar_lote(run.id)

    assert resultado["continuar"] is False
    assert resultado["run"]["estado"] == "done"
    assert resultado["run"]["procesados"] == 2
    assert resultado["run"]["con_senal"] == 2
    assert resultado["run"]["pendientes"] == 0
    guardado = db.session.get(PicksSignalRun, run.id)
    assert guardado.status == "done"
    assert all(item.status == "done" for item in guardado.items)


def test_pausar_y_reanudar_corrida(app, monkeypatch):
    job = _job()
    _reporte(job)
    run = picks_signal_runs.crear_corrida(
        job.id, "seiscomp", _filas()
    )
    _preparar_analisis(monkeypatch)

    picks_signal_runs.pausar(run.id)
    pausada = picks_signal_runs.procesar_lote(run.id)
    assert pausada["estado"] == "sin_cambios"
    assert db.session.get(PicksSignalRun, run.id).status == "paused"

    picks_signal_runs.reanudar(run.id)
    final = picks_signal_runs.procesar_lote(run.id)
    assert final["run"]["estado"] == "done"
    assert final["run"]["procesados"] == 2


def test_cancelar_corrida_no_procesa(app):
    job = _job()
    run = picks_signal_runs.crear_corrida(
        job.id, "seiscomp", _filas()
    )
    picks_signal_runs.cancelar(run.id)
    resultado = picks_signal_runs.procesar_lote(run.id)
    assert resultado["estado"] == "sin_cambios"
    assert db.session.get(PicksSignalRun, run.id).status == "cancelled"


def test_error_de_servicio_pausa_y_deja_pendiente(app, monkeypatch):
    job = _job()
    _reporte(job)
    run = picks_signal_runs.crear_corrida(
        job.id, "seiscomp", _filas()
    )
    _preparar_analisis(monkeypatch)

    def falla(*_args, **_kwargs):
        raise availability.AvailabilityError("sin servicio")

    monkeypatch.setattr(
        picks_signal_runs.picks_signal, "analizar_evento", falla
    )
    resultado = picks_signal_runs.procesar_lote(run.id)
    assert resultado["run"]["estado"] == "paused"
    assert resultado["run"]["procesados"] == 0
    guardado = db.session.get(PicksSignalRun, run.id)
    assert all(item.status == "pending" for item in guardado.items)
