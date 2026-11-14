"""Solicitudes de revisión con eventos y PDF adjunto."""

from __future__ import annotations

from pathlib import Path

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload, selectinload

from ..extensions import db
from ..models import ESTADOS_REVISION, ReviewRequest, User, utcnow
from ..security import (
    alcance_total,
    permiso_requerido,
    puede_ver_trabajo,
    tiene_permiso,
)
from ..services import formatting
from ..services.analysts import usuarios_analistas_activos
from ..services.audit import registrar
from ..services.workspace import ruta_workspace

revisiones_bp = Blueprint("revisiones", __name__, url_prefix="/revisiones")

ESTADOS_ETIQUETA = {
    "notificada": "Notificada",
    "en_proceso": "En proceso",
    "cerrada": "Cerrada",
}
ESTADOS_BADGE = {
    "notificada": "text-bg-warning text-dark",
    "en_proceso": "text-bg-primary",
    "cerrada": "text-bg-success",
}


def _puede_ver(solicitud: ReviewRequest, usuario) -> bool:
    if not tiene_permiso(usuario, "revisiones.ver"):
        return False
    if alcance_total(usuario):
        return True
    return solicitud.assigned_to_id == getattr(usuario, "id", None)


def _solicitud(request_id: int) -> ReviewRequest:
    solicitud = db.session.get(ReviewRequest, request_id)
    if solicitud is None:
        abort(404)
    if not _puede_ver(solicitud, current_user):
        abort(403)
    return solicitud


def _es_asignado(solicitud: ReviewRequest) -> bool:
    return solicitud.assigned_to_id == getattr(current_user, "id", None)


def _analistas() -> list[User]:
    return usuarios_analistas_activos()


def _volver(solicitud: ReviewRequest) -> str:
    return url_for("revisiones.detalle", request_id=solicitud.id)


@revisiones_bp.get("")
@login_required
@permiso_requerido("revisiones.ver")
def index():
    estado = request.args.get("estado", "").strip()
    if estado not in ESTADOS_REVISION:
        estado = ""
    try:
        analista_id = int(request.args.get("analista", ""))
    except (TypeError, ValueError):
        analista_id = None

    consulta = (
        db.select(ReviewRequest)
        .options(
            selectinload(ReviewRequest.events),
            joinedload(ReviewRequest.created_by),
            joinedload(ReviewRequest.assigned_to),
        )
        .order_by(
            ReviewRequest.notified_at.desc(), ReviewRequest.id.desc()
        )
    )
    ver_todas = alcance_total(current_user)
    if not ver_todas:
        consulta = consulta.where(
            ReviewRequest.assigned_to_id == current_user.id
        )
    if estado:
        consulta = consulta.where(ReviewRequest.status == estado)
    if analista_id is not None:
        consulta = consulta.where(
            ReviewRequest.assigned_to_id == analista_id
        )
    solicitudes = db.session.execute(consulta).scalars().all()

    return render_template(
        "revisiones/index.html",
        solicitudes=solicitudes,
        estado=estado,
        analista_id=analista_id,
        analistas=_analistas(),
        estados=ESTADOS_REVISION,
        etiquetas_estado=ESTADOS_ETIQUETA,
        badges_estado=ESTADOS_BADGE,
        alcance_total=ver_todas,
    )


@revisiones_bp.get("/<int:request_id>")
@login_required
@permiso_requerido("revisiones.ver")
def detalle(request_id: int):
    solicitud = _solicitud(request_id)
    puede_responder = tiene_permiso(current_user, "revisiones.responder")
    return render_template(
        "revisiones/detail.html",
        solicitud=solicitud,
        etiqueta_estado=ESTADOS_ETIQUETA.get(
            solicitud.status, solicitud.status
        ),
        badge_estado=ESTADOS_BADGE.get(
            solicitud.status, "text-bg-light text-dark"
        ),
        puede_aceptar=(
            puede_responder
            and _es_asignado(solicitud)
            and solicitud.status == "notificada"
        ),
        puede_cerrar=(
            puede_responder
            and _es_asignado(solicitud)
            and solicitud.status == "en_proceso"
        ),
        puede_descargar=bool(solicitud.report_path),
        puede_ver_job=bool(
            solicitud.job is not None
            and puede_ver_trabajo(solicitud.job, current_user)
        ),
        formato=formatting,
    )


@revisiones_bp.get("/<int:request_id>/pdf")
@login_required
@permiso_requerido("revisiones.ver")
def pdf(request_id: int):
    solicitud = _solicitud(request_id)
    if not solicitud.report_path:
        abort(404)
    workspace = ruta_workspace(solicitud.job_id).resolve()
    ruta = (workspace / solicitud.report_path).resolve()
    if not ruta.is_file() or not ruta.is_relative_to(workspace):
        abort(404)
    return send_file(
        ruta,
        as_attachment=True,
        download_name=solicitud.report_name or Path(ruta).name,
        max_age=0,
    )


@revisiones_bp.post("/<int:request_id>/aceptar")
@login_required
@permiso_requerido("revisiones.responder")
def aceptar(request_id: int):
    solicitud = _solicitud(request_id)
    if not _es_asignado(solicitud):
        abort(403)
    if solicitud.status != "notificada":
        flash("La solicitud ya no está pendiente de aceptación.", "warning")
        return redirect(_volver(solicitud))
    solicitud.status = "en_proceso"
    solicitud.accepted_at = utcnow()
    db.session.commit()
    registrar(
        "revision.aceptar",
        f"review:{solicitud.id}",
        {"job": solicitud.job_id, "analista": solicitud.assigned_to_id},
    )
    flash("Solicitud aceptada. Ya está en proceso.", "success")
    return redirect(_volver(solicitud))


@revisiones_bp.post("/<int:request_id>/cerrar")
@login_required
@permiso_requerido("revisiones.responder")
def cerrar(request_id: int):
    solicitud = _solicitud(request_id)
    if not _es_asignado(solicitud):
        abort(403)
    if solicitud.status != "en_proceso":
        flash("La solicitud debe estar en proceso para cerrarla.", "warning")
        return redirect(_volver(solicitud))
    antecedentes = request.form.get("antecedentes", "").strip()
    if not antecedentes:
        flash("Escriba los antecedentes de lo realizado.", "danger")
        return redirect(_volver(solicitud))
    solicitud.status = "cerrada"
    solicitud.closed_at = utcnow()
    solicitud.closing_note = antecedentes
    db.session.commit()
    registrar(
        "revision.cerrar",
        f"review:{solicitud.id}",
        {
            "job": solicitud.job_id,
            "analista": solicitud.assigned_to_id,
            "antecedentes": antecedentes,
        },
    )
    flash("Solicitud cerrada con los antecedentes registrados.", "success")
    return redirect(_volver(solicitud))
