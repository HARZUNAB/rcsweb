"""Corridas persistentes del análisis de señal."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.domain.catalogs import canonical
from app.extensions import db
from app.models import PicksSignalRun, PicksSignalRunItem, utcnow
from app.services import availability, picks_coverage, picks_signal
from app.services.workspace import ruta_workspace

LOG = logging.getLogger(__name__)

ESTADOS_ACTIVOS = {"queued", "running", "paused"}
ESTADOS_FINALES = {"done", "cancelled", "error"}
LOTE_DEFECTO = 25
MAX_ITEMS = 5000


def _iso(valor: datetime | None) -> str:
    return valor.isoformat() if valor is not None else ""


def _pendientes(run: PicksSignalRun) -> int:
    return int(
        db.session.scalar(
            select(func.count())
            .select_from(PicksSignalRunItem)
            .where(
                PicksSignalRunItem.run_id == run.id,
                PicksSignalRunItem.status.in_(("pending", "running")),
            )
        )
        or 0
    )


def estado_corrida(run: PicksSignalRun) -> dict:
    estado = run.status
    return {
        "run_id": run.id,
        "job_id": run.job_id,
        "fuente": run.source_id,
        "estado": estado,
        "alcance": run.scope,
        "total": run.total,
        "procesados": run.processed,
        "con_senal": run.con_senal,
        "sin_senal": run.sin_senal,
        "sin_datos": run.sin_datos,
        "errores": run.errores,
        "pendientes": _pendientes(run),
        "evento": run.current_event or "",
        "mensaje": run.message or "",
        "creada": _iso(run.created_at),
        "iniciada": _iso(run.started_at),
        "terminada": _iso(run.finished_at),
        "puede_pausar": estado in ("queued", "running"),
        "puede_reanudar": estado == "paused",
        "puede_cancelar": estado in ESTADOS_ACTIVOS,
    }


def corrida_activa(job_id: str, fuente: str) -> PicksSignalRun | None:
    return db.session.scalar(
        select(PicksSignalRun)
        .where(
            PicksSignalRun.job_id == job_id,
            PicksSignalRun.source_id == fuente,
            PicksSignalRun.status.in_(ESTADOS_ACTIVOS),
        )
        .order_by(PicksSignalRun.created_at.desc())
        .limit(1)
    )


def crear_corrida(
    job_id: str,
    fuente: str,
    filas: list[dict],
    *,
    evento_ids: set[str] | None = None,
    alcance: str = "todos",
    batch_size: int = LOTE_DEFECTO,
    created_by_id: int | None = None,
    incluir_terminales: bool = False,
) -> PicksSignalRun | None:
    """Crea la corrida con los eventos pendientes en el orden recibido."""
    seleccionados = []
    vistos: set[str] = set()
    for fila in filas:
        if not incluir_terminales and not fila.get("senal_pendiente"):
            continue
        event_id = str(fila.get("evento") or "").strip()
        if not event_id or event_id in vistos:
            continue
        if evento_ids is not None and event_id not in evento_ids:
            continue
        vistos.add(event_id)
        seleccionados.append(event_id)
        if len(seleccionados) >= MAX_ITEMS:
            break
    if not seleccionados:
        return None
    run = PicksSignalRun(
        job_id=job_id,
        source_id=fuente,
        status="queued",
        scope=alcance,
        total=len(seleccionados),
        batch_size=max(1, int(batch_size)),
        created_by_id=created_by_id,
    )
    db.session.add(run)
    db.session.flush()
    for posicion, event_id in enumerate(seleccionados, start=1):
        db.session.add(
            PicksSignalRunItem(
                run_id=run.id,
                event_id=event_id,
                position=posicion,
                status="pending",
            )
        )
    db.session.commit()
    return run


def pausar(run_id: str) -> PicksSignalRun | None:
    run = db.session.get(PicksSignalRun, run_id)
    if run is None:
        return None
    if run.status in ("queued", "running"):
        run.status = "paused"
        run.message = "Pausada por el usuario."
        db.session.commit()
    return run


def reanudar(run_id: str) -> PicksSignalRun | None:
    run = db.session.get(PicksSignalRun, run_id)
    if run is None:
        return None
    if run.status == "paused":
        run.status = "queued"
        run.message = ""
        db.session.commit()
    return run


def cancelar(run_id: str) -> PicksSignalRun | None:
    run = db.session.get(PicksSignalRun, run_id)
    if run is None:
        return None
    if run.status in ESTADOS_ACTIVOS:
        run.status = "cancelled"
        run.message = "Cancelada por el usuario."
        run.finished_at = utcnow()
        db.session.commit()
    return run


def _guardar_resumen(run: PicksSignalRun) -> None:
    picks_signal.guardar_resumen(
        ruta_workspace(run.job_id),
        run.source_id,
        {
            "job_id": run.job_id,
            "fuente": run.source_id,
            "corrida": run.id,
            "eventos": run.processed,
            "con_senal": run.con_senal,
            "sin_senal": run.sin_senal,
            "sin_datos": run.sin_datos,
            "errores": run.errores,
            "actualizado": datetime.now(UTC).isoformat(),
        },
    )


def procesar_lote(
    run_id: str,
    *,
    limite: int | None = None,
    correlacionar_fn=None,
) -> dict:
    """Procesa un lote de la corrida y deja el estado en la base."""
    run = db.session.get(PicksSignalRun, run_id)
    if run is None:
        return {"estado": "error", "mensaje": "La corrida no existe."}
    if run.status not in ("queued", "running"):
        return {"estado": "sin_cambios", "run": estado_corrida(run)}
    if run.status == "queued":
        run.status = "running"
        run.started_at = run.started_at or utcnow()
        run.message = ""
        db.session.commit()

    workspace = ruta_workspace(run.job_id)
    filas = {
        str(fila.get("evento") or ""): fila
        for fila in picks_coverage.leer(workspace, run.source_id)
    }
    eventos = {
        str(evento.get("event_id") or ""): evento
        for evento in canonical.leer_canonico(workspace, run.source_id)
    }
    arribos: dict[str, list[dict]] = defaultdict(list)
    for arribo in canonical.leer_arribos(workspace, run.source_id):
        event_id = str(arribo.get("event_id") or "").strip()
        if event_id:
            arribos[event_id].append(arribo)

    items = db.session.scalars(
        select(PicksSignalRunItem)
        .where(
            PicksSignalRunItem.run_id == run.id,
            PicksSignalRunItem.status.in_(("pending", "running")),
        )
        .order_by(PicksSignalRunItem.position)
        .limit(limite or run.batch_size)
    ).all()
    if not items:
        run.status = "done"
        run.finished_at = utcnow()
        run.message = "Corrida completada."
        db.session.commit()
        _guardar_resumen(run)
        return {"estado": "ok", "run": estado_corrida(run), "continuar": False}

    cambios: dict[str, dict] = {}
    for item in items:
        db.session.refresh(run)
        if run.status != "running":
            break
        event_id = str(item.event_id)
        item.status = "running"
        run.current_event = event_id
        db.session.commit()

        fila = filas.get(event_id)
        evento = eventos.get(event_id)
        if fila is None or evento is None:
            item.status = "error"
            item.error = "Sin datos del evento en el reporte o canónico."
            run.errores += 1
            run.processed += 1
            db.session.commit()
            continue
        try:
            resultado = picks_signal.analizar_evento(
                evento,
                fila.get("detalle") or [],
                arribos.get(event_id, []),
                correlacionar_fn=correlacionar_fn,
            )
        except availability.AvailabilityError as exc:
            item.status = "pending"
            item.error = str(exc)
            run.status = "paused"
            run.message = (
                "Servicio de correlación no disponible. "
                "Reanude cuando esté operativo."
            )
            db.session.commit()
            break
        except Exception as exc:  # noqa: BLE001 - se registra por evento
            LOG.exception("Error al analizar %s en corrida %s", event_id, run.id)
            item.status = "error"
            item.error = str(exc)
            run.errores += 1
            run.processed += 1
            db.session.commit()
            continue

        picks_signal.guardar_resultado(run.source_id, fila, resultado)
        cambios[event_id] = {
            "senal_n": resultado["senal_n"],
            "senal_estaciones": resultado["senal_estaciones"],
            "senal_estado": resultado["senal_estado"],
            "senal_actualizado": datetime.now(UTC).isoformat(),
        }
        item.status = "done"
        item.error = None
        item.analyzed_at = utcnow()
        run.processed += 1
        if resultado["senal_estado"] == "sin_datos":
            run.sin_datos += 1
        elif resultado["senal_n"]:
            run.con_senal += 1
        else:
            run.sin_senal += 1
        db.session.commit()

    if cambios:
        picks_coverage.actualizar_senales(workspace, run.source_id, cambios)

    db.session.refresh(run)
    pendientes = _pendientes(run)
    if run.status == "running" and pendientes == 0:
        run.status = "done"
        run.finished_at = utcnow()
        run.message = "Corrida completada."
        db.session.commit()
        _guardar_resumen(run)
    elif run.status == "running":
        run.updated_at = utcnow()
        db.session.commit()
    return {
        "estado": "ok",
        "run": estado_corrida(run),
        "continuar": run.status == "running" and pendientes > 0,
    }


__all__ = [
    "ESTADOS_ACTIVOS",
    "ESTADOS_FINALES",
    "LOTE_DEFECTO",
    "MAX_ITEMS",
    "cancelar",
    "corrida_activa",
    "crear_corrida",
    "estado_corrida",
    "pausar",
    "procesar_lote",
    "reanudar",
]
