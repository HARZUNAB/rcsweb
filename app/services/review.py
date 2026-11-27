"""Consultas y creación de solicitudes de revisión."""

from __future__ import annotations

from datetime import datetime

from flask import current_app
from sqlalchemy.orm import joinedload, selectinload

from ..extensions import db
from ..models import ReviewRequest, ReviewRequestEvent, User
from ..security import tiene_rol
from .analysts import usuarios_analistas_activos

ESTADOS_ACTIVOS = ("borrador", "notificada", "en_proceso")


def usuarios_analistas() -> list[User]:
    return usuarios_analistas_activos()


def supervisores_con_correo() -> list[User]:
    """Usuarios activos con rol supervisor y correo, para copias del aviso."""
    usuarios = db.session.execute(
        db.select(User).order_by(User.email, User.username)
    ).scalars()
    return [
        usuario
        for usuario in usuarios
        if usuario.active
        and str(usuario.email or "").strip()
        and tiene_rol(usuario, "supervisor")
    ]


def copias_unicas(correos, excluir: str = "") -> list[str]:
    """Normaliza y deduplica correos; omite el destinatario principal."""
    vistos = {
        str(excluir or "").strip().casefold()
    } - {""}
    salida: list[str] = []
    for correo in correos or []:
        limpio = str(correo or "").strip()
        clave = limpio.casefold()
        if not limpio or clave in vistos:
            continue
        vistos.add(clave)
        salida.append(limpio)
    return salida


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
        "creada_por_id": solicitud.created_by_id,
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


def notificar_desde_formulario(valor, defecto: bool = False) -> bool:
    """Interpreta la elección de enviar el correo de notificación.

    Un valor vacío o ausente usa ``defecto``; los formularios envían ``1`` o
    ``0`` de forma explícita.
    """
    if valor is None or not str(valor).strip():
        return bool(defecto)
    return str(valor).strip().lower() in {"1", "true", "on", "si", "sí"}


def leer_notificacion(form, notificar: bool):
    """Copias y adjunto elegidos para el correo de la solicitud."""
    if not notificar:
        return [], False, None
    modo = str(
        current_app.config.get("RCS_NOTIFICACION_MODO", "correo")
    ).strip().lower()
    adjuntar = str(form.get("adjuntar_pdf") or "").strip().lower() in {
        "1",
        "true",
        "on",
        "si",
        "sí",
    }
    if modo == "correo" and not adjuntar:
        return [], adjuntar, "Para notificar debe adjuntar el PDF."

    obligatorias = bool(
        current_app.config.get(
            "RCS_NOTIFICACION_COPIAS_OBLIGATORIAS", False
        )
    )
    agregar = str(form.get("agregar_copias") or "").strip().lower() in {
        "1",
        "true",
        "on",
        "si",
        "sí",
    }
    if not agregar and not obligatorias:
        return [], adjuntar, None

    disponibles = supervisores_con_correo()
    requeridas = min(2, len(disponibles)) if obligatorias else 0
    elegidos = []
    vistos = set()
    for clave in ("cc_1", "cc_2"):
        valor = str(form.get(clave) or "").strip()
        if not valor:
            continue
        try:
            usuario = db.session.get(User, int(valor))
        except (TypeError, ValueError):
            usuario = None
        if (
            usuario is None
            or not usuario.active
            or not str(usuario.email or "").strip()
            or not tiene_rol(usuario, "supervisor")
        ):
            return [], adjuntar, "Seleccione direcciones de copia válidas."
        if usuario.id in vistos:
            return [], adjuntar, "Las direcciones de copia deben ser distintas."
        vistos.add(usuario.id)
        elegidos.append(usuario)
    if len(elegidos) < requeridas:
        mensaje = (
            "Seleccione dos direcciones de copia."
            if requeridas >= 2
            else "Seleccione una dirección de copia."
        )
        return [], adjuntar, mensaje
    return (
        [str(usuario.email).strip() for usuario in elegidos],
        adjuntar,
        None,
    )


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
    kind: str = "solucion",
    notificar: bool = True,
    email_cc: str = "",
    email_attach_report: bool = False,
    status: str = "notificada",
    email_skipped: bool | None = None,
) -> ReviewRequest:
    """Crea la solicitud y sus eventos; el llamador controla la transacción."""
    solicitud = ReviewRequest(
        job_id=job_id,
        source_id=source_id,
        created_by_id=created_by_id,
        assigned_to_id=assigned_to_id,
        status=status,
        kind=kind,
        note=note or None,
        report_path=report_path,
        report_name=report_name,
        report_format=report_format,
        notified_at=notified_at,
        email_skipped=(
            not notificar if email_skipped is None else bool(email_skipped)
        ),
        email_cc=email_cc or None,
        email_attach_report=bool(email_attach_report),
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
                ondas=evento.get("ondas") or None,
            )
        )
    db.session.flush()
    return solicitud
