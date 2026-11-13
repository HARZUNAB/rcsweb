"""Consultas y creación de solicitudes de revisión."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import joinedload, selectinload

from ..extensions import db
from ..models import ReviewRequest, ReviewRequestEvent, User

ESTADOS_ACTIVOS = ("notificada", "en_proceso")


def usuarios_analistas() -> list[User]:
    return (
        db.session.execute(
            db.select(User)
            .where(User.role == "analista", User.active.is_(True))
            .order_by(User.username)
        )
        .scalars()
        .all()
    )


def _resumen(solicitud: ReviewRequest) -> dict:
    return {
        "id": solicitud.id,
        "estado": solicitud.status,
        "activa": solicitud.status in ESTADOS_ACTIVOS,
        "asignada": (
            solicitud.assigned_to.username
            if solicitud.assigned_to is not None
            else ""
        ),
        "asignada_id": solicitud.assigned_to_id,
        "notificada": solicitud.notified_at,
        "cerrada": solicitud.closed_at,
    }


def mapa_solicitudes(job_id: str, source_id: str) -> dict[str, dict]:
    """Última solicitud por evento, priorizando las activas."""
    solicitudes = (
        db.session.execute(
            db.select(ReviewRequest)
            .options(
                selectinload(ReviewRequest.events),
                joinedload(ReviewRequest.assigned_to),
            )
            .where(
                ReviewRequest.job_id == job_id,
                ReviewRequest.source_id == source_id,
            )
            .order_by(
                ReviewRequest.notified_at.desc(), ReviewRequest.id.desc()
            )
        )
        .scalars()
        .all()
    )
    mapa: dict[str, dict] = {}
    for solicitud in solicitudes:
        resumen = _resumen(solicitud)
        for evento in solicitud.events:
            if evento.source_id != source_id:
                continue
            actual = mapa.get(evento.event_id)
            if actual is None:
                mapa[evento.event_id] = resumen
            elif not actual["activa"] and resumen["activa"]:
                mapa[evento.event_id] = resumen
    return mapa


def solicitud_de_evento(
    job_id: str, source_id: str, event_id: str
) -> dict | None:
    return mapa_solicitudes(job_id, source_id).get(event_id)


def conflictos(
    job_id: str, source_id: str, event_ids: list[str]
) -> list[dict]:
    """Solicitudes activas que ya contienen alguno de los eventos."""
    if not event_ids:
        return []
    filas = db.session.execute(
        db.select(ReviewRequestEvent, ReviewRequest)
        .join(
            ReviewRequest,
            ReviewRequestEvent.request_id == ReviewRequest.id,
        )
        .where(
            ReviewRequest.job_id == job_id,
            ReviewRequest.source_id == source_id,
            ReviewRequest.status.in_(ESTADOS_ACTIVOS),
            ReviewRequestEvent.source_id == source_id,
            ReviewRequestEvent.event_id.in_(event_ids),
        )
        .order_by(ReviewRequest.notified_at.desc())
    ).all()
    return [
        {
            "evento": evento.event_id,
            "solicitud_id": solicitud.id,
            "estado": solicitud.status,
            "asignada": (
                solicitud.assigned_to.username
                if solicitud.assigned_to is not None
                else ""
            ),
        }
        for evento, solicitud in filas
    ]


def crear_solicitud(
    *,
    job_id: str,
    source_id: str,
    created_by_id: int | None,
    assigned_to_id: int | None,
    note: str,
    notified_at: datetime,
    eventos: list[dict],
    report_path: str,
    report_name: str,
    report_format: str,
) -> ReviewRequest:
    """Crea la solicitud y sus eventos; el llamador controla la transacción."""
    solicitud = ReviewRequest(
        job_id=job_id,
        source_id=source_id,
        created_by_id=created_by_id,
        assigned_to_id=assigned_to_id,
        status="notificada",
        note=note or None,
        report_path=report_path,
        report_name=report_name,
        report_format=report_format,
        notified_at=notified_at,
    )
    db.session.add(solicitud)
    db.session.flush()
    for evento in eventos:
        db.session.add(
            ReviewRequestEvent(
                request_id=solicitud.id,
                source_id=source_id,
                event_id=evento["evento"],
                source_event_id=evento.get("id_evento_fuente", ""),
                fila_catalogo=evento.get("fila_catalogo"),
                event_time=evento.get("fecha_hora", ""),
                latitude=evento.get("latitude"),
                longitude=evento.get("longitude"),
                depth_km=evento.get("depth_km"),
                magnitude=evento.get("magnitude"),
                magnitude_type=evento.get("magnitude_type", ""),
                analyst=evento.get("analista", ""),
                priority=evento.get("prioridad", ""),
                motive=evento.get("motivo", ""),
            )
        )
    db.session.flush()
    return solicitud
