"""Solicitudes de revisión con eventos y PDF adjunto."""

from __future__ import annotations

import shutil
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload, selectinload
from werkzeug.utils import secure_filename

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
from ..services.workspace import guardar_archivo_limitado, ruta_workspace

revisiones_bp = Blueprint("revisiones", __name__, url_prefix="/revisiones")

EVIDENCIA_EXTENSIONES = {
    "pdf",
    "png",
    "jpg",
    "jpeg",
    "webp",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "txt",
    "csv",
    "zip",
}

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


def _url_actualizada_valida(url: str) -> bool:
    if not url or len(url) > 1000:
        return False
    partes = urlparse(url)
    return partes.scheme in {"http", "https"} and bool(partes.netloc)


def _guardar_evidencia(solicitud: ReviewRequest, archivo) -> dict | None:
    nombre_original = (getattr(archivo, "filename", "") or "").strip()
    if not nombre_original:
        return None
    nombre = secure_filename(nombre_original) or "evidencia"
    extension = Path(nombre).suffix.lower().lstrip(".")
    if extension not in EVIDENCIA_EXTENSIONES:
        raise ValueError(
            "Formato de evidencia no permitido. Use PDF, imágenes, "
            "DOC/DOCX, XLS/XLSX, TXT, CSV o ZIP."
        )
    max_mb = int(current_app.config.get("RCS_EVIDENCIA_MAX_MB", 20) or 20)
    max_bytes = max_mb * 1024 * 1024
    workspace = ruta_workspace(solicitud.job_id)
    carpeta = workspace / "revisiones" / "evidencia" / str(solicitud.id)
    destino = carpeta / f"{uuid4().hex[:12]}_{nombre}"
    try:
        tamano, sha256 = guardar_archivo_limitado(
            archivo, destino, max_bytes
        )
    except ValueError:
        raise ValueError(
            f"La evidencia supera el tamaño máximo de {max_mb} MB."
        ) from None
    return {
        "path": str(destino.relative_to(workspace)),
        "name": nombre_original,
        "size": tamano,
        "sha256": sha256,
    }


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
        puede_eliminar=tiene_permiso(
            current_user, "revisiones.eliminar"
        ),
        puede_ver_job=bool(
            solicitud.job is not None
            and puede_ver_trabajo(solicitud.job, current_user)
        ),
        formato=formatting,
    )


@revisiones_bp.post("/<int:request_id>/eliminar")
@login_required
@permiso_requerido("revisiones.eliminar")
def eliminar(request_id: int):
    """Elimina una solicitud, sus eventos y sus archivos asociados."""
    solicitud = _solicitud(request_id)
    job_id = solicitud.job_id
    source_id = solicitud.source_id
    eventos = [evento.event_id for evento in solicitud.events]
    report_path = solicitud.report_path
    workspace = ruta_workspace(job_id)

    if report_path:
        try:
            (workspace / report_path).unlink(missing_ok=True)
        except OSError:
            current_app.logger.warning(
                "No se pudo borrar el informe %s", report_path
            )
    try:
        shutil.rmtree(
            workspace / "revisiones" / "evidencia" / str(request_id),
            ignore_errors=True,
        )
    except OSError:
        current_app.logger.warning(
            "No se pudo borrar la evidencia de la solicitud %s", request_id
        )

    db.session.delete(solicitud)
    db.session.commit()
    registrar(
        "revision.eliminar",
        f"review:{request_id}",
        {
            "job": job_id,
            "fuente": source_id,
            "eventos": eventos,
        },
        user_id=current_user.id,
    )
    flash(f"Solicitud #{request_id} eliminada.", "success")
    return redirect(url_for("revisiones.index"))


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


@revisiones_bp.get("/<int:request_id>/evidencia")
@login_required
@permiso_requerido("revisiones.ver")
def evidencia(request_id: int):
    solicitud = _solicitud(request_id)
    if not solicitud.evidence_path:
        abort(404)
    workspace = ruta_workspace(solicitud.job_id).resolve()
    ruta = (workspace / solicitud.evidence_path).resolve()
    if not ruta.is_file() or not ruta.is_relative_to(workspace):
        abort(404)
    return send_file(
        ruta,
        as_attachment=True,
        download_name=solicitud.evidence_name or Path(ruta).name,
        max_age=0,
    )


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

    cambios: dict[int, dict] = {}
    for evento in solicitud.events:
        marcado = request.form.get(f"cambio_{evento.id}") in {
            "1",
            "on",
            "true",
            "si",
            "sí",
        }
        despublicado = request.form.get(
            f"despublicado_{evento.id}"
        ) in {
            "1",
            "on",
            "true",
            "si",
            "sí",
        }
        url = request.form.get(f"url_{evento.id}", "").strip()
        observacion = request.form.get(
            f"observacion_{evento.id}", ""
        ).strip()
        if len(observacion) > 1000:
            flash(
                "La observación del evento "
                f"{evento.event_id} no puede superar 1000 caracteres.",
                "danger",
            )
            return redirect(_volver(solicitud))
        if not marcado:
            url = ""
        if marcado and not despublicado and not _url_actualizada_valida(url):
            flash(
                "Indique una URL actualizada válida para el evento "
                f"{evento.event_id}.",
                "danger",
            )
            return redirect(_volver(solicitud))
        if url and not _url_actualizada_valida(url):
            flash(
                "La URL del evento "
                f"{evento.event_id} no es válida.",
                "danger",
            )
            return redirect(_volver(solicitud))
        cambios[evento.id] = {
            "parameters_changed": marcado,
            "unpublished": despublicado,
            "updated_url": url or None,
            "observation": observacion or None,
        }

    evidencia = None
    archivo = request.files.get("evidencia")
    if archivo is not None and (archivo.filename or "").strip():
        try:
            evidencia = _guardar_evidencia(solicitud, archivo)
        except ValueError as exc:
            flash(str(exc), "danger")
            return redirect(_volver(solicitud))

    solicitud.status = "cerrada"
    solicitud.closed_at = utcnow()
    solicitud.closing_note = antecedentes
    if evidencia:
        solicitud.evidence_path = evidencia["path"]
        solicitud.evidence_name = evidencia["name"]
        solicitud.evidence_size = evidencia["size"]
        solicitud.evidence_sha256 = evidencia["sha256"]
        solicitud.evidence_uploaded_at = utcnow()
    for evento in solicitud.events:
        cambio = cambios[evento.id]
        evento.parameters_changed = cambio["parameters_changed"]
        evento.unpublished = cambio["unpublished"]
        evento.updated_url = cambio["updated_url"]
        evento.observation = cambio["observation"]

    try:
        db.session.commit()
    except Exception:  # noqa: BLE001 - se conserva la solicitud abierta
        db.session.rollback()
        if evidencia:
            ruta = (
                ruta_workspace(solicitud.job_id) / evidencia["path"]
            ).resolve()
            ruta.unlink(missing_ok=True)
        flash("No se pudo cerrar la solicitud.", "danger")
        return redirect(_volver(solicitud))

    registrar(
        "revision.cerrar",
        f"review:{solicitud.id}",
        {
            "job": solicitud.job_id,
            "analista": solicitud.assigned_to_id,
            "antecedentes": antecedentes,
            "evidencia": (
                {
                    "nombre": evidencia["name"],
                    "tamano": evidencia["size"],
                    "sha256": evidencia["sha256"],
                }
                if evidencia
                else None
            ),
            "cambios": [
                {
                    "evento": evento.event_id,
                    "cambio_parametros": evento.parameters_changed,
                    "despublicado": evento.unpublished,
                    "url_actualizada": evento.updated_url,
                    "observacion": evento.observation,
                }
                for evento in solicitud.events
            ],
        },
    )
    flash("Solicitud cerrada con los antecedentes registrados.", "success")
    return redirect(_volver(solicitud))
