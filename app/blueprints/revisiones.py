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
from sqlalchemy import and_, or_
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
from ..services import formatting, notifications, review
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
    "borrador": "Borrador",
    "notificada": "Notificada",
    "en_proceso": "En proceso",
    "cerrada": "Cerrada",
}
ESTADOS_BADGE = {
    "borrador": "text-bg-info text-dark",
    "notificada": "text-bg-warning text-dark",
    "en_proceso": "text-bg-primary",
    "cerrada": "text-bg-success",
}

MARCAS_REVISION = {"1", "true", "on", "si", "sí"}


def _puede_ver(solicitud: ReviewRequest, usuario) -> bool:
    if not tiene_permiso(usuario, "revisiones.ver"):
        return False
    if alcance_total(usuario):
        return True
    if solicitud.status == "borrador":
        return solicitud.created_by_id == getattr(usuario, "id", None)
    return solicitud.assigned_to_id == getattr(usuario, "id", None)


def _puede_gestionar_borrador(solicitud: ReviewRequest) -> bool:
    if solicitud.status != "borrador":
        return False
    if alcance_total(current_user):
        return True
    return solicitud.created_by_id == getattr(current_user, "id", None)


def _puede_descartar_borrador(solicitud: ReviewRequest) -> bool:
    if not _puede_gestionar_borrador(solicitud):
        return False
    return (
        solicitud.created_by_id == getattr(current_user, "id", None)
        or tiene_permiso(current_user, "revisiones.eliminar")
    )


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
            or_(
                ReviewRequest.created_by_id == current_user.id,
                and_(
                    ReviewRequest.status != "borrador",
                    ReviewRequest.assigned_to_id == current_user.id,
                ),
            )
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
    gestion_borrador = _puede_gestionar_borrador(solicitud)
    return render_template(
        "revisiones/detail.html",
        solicitud=solicitud,
        etiqueta_estado=ESTADOS_ETIQUETA.get(
            solicitud.status, solicitud.status
        ),
        badge_estado=ESTADOS_BADGE.get(
            solicitud.status, "text-bg-light text-dark"
        ),
        puede_enviar=(
            gestion_borrador
            and tiene_permiso(current_user, "revisiones.crear")
        ),
        puede_descartar=_puede_descartar_borrador(solicitud),
        supervisores_copia=(
            review.supervisores_con_correo() if gestion_borrador else []
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


def _borrar_archivos(solicitud: ReviewRequest, request_id: int) -> None:
    workspace = ruta_workspace(solicitud.job_id)
    if solicitud.report_path:
        try:
            (workspace / solicitud.report_path).unlink(missing_ok=True)
        except OSError:
            current_app.logger.warning(
                "No se pudo borrar el informe %s", solicitud.report_path
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


@revisiones_bp.post("/<int:request_id>/enviar")
@login_required
@permiso_requerido("revisiones.ver")
def enviar(request_id: int):
    """Envía un borrador revisado y, si corresponde, notifica por correo."""
    solicitud = _solicitud(request_id)
    if not _puede_gestionar_borrador(solicitud):
        abort(403)
    if not tiene_permiso(current_user, "revisiones.crear"):
        abort(403)
    if not solicitud.report_path:
        flash(
            "El borrador no tiene informe. No se puede enviar.",
            "danger",
        )
        return redirect(_volver(solicitud))
    if request.form.get("revisado") not in MARCAS_REVISION:
        flash(
            "Marque «He revisado el PDF» antes de enviar la solicitud.",
            "danger",
        )
        return redirect(_volver(solicitud))

    notificar = review.notificar_desde_formulario(
        request.form.get("notificar"),
        current_app.config.get("RCS_NOTIFICAR_REVISION_DEFAULT", False),
    )
    copias, adjuntar_pdf, error_notificacion = review.leer_notificacion(
        request.form, notificar
    )
    if error_notificacion:
        flash(error_notificacion, "danger")
        return redirect(_volver(solicitud))

    if notificar:
        solicitud.email_cc = ", ".join(copias) or None
        solicitud.email_attach_report = bool(adjuntar_pdf)
        solicitud.email_skipped = False
        solicitud.email_error = None
        enviado = notifications.enviar_solicitud(
            solicitud, base_url=request.host_url.rstrip("/")
        )
        if not enviado:
            registrar(
                "revision.enviar",
                f"review:{solicitud.id}",
                {
                    "ok": False,
                    "destinatario": solicitud.email_to or "",
                    "cc": solicitud.email_cc or "",
                    "adjunto": bool(solicitud.email_attach_report),
                    "error": solicitud.email_error or "",
                },
                user_id=current_user.id,
            )
            flash(
                "No se pudo enviar el correo: "
                f"{solicitud.email_error or 'error desconocido'}. "
                "El borrador sigue disponible para reintentar.",
                "danger",
            )
            return redirect(_volver(solicitud))
        mensaje = (
            "Solicitud enviada y correo notificado a "
            f"{solicitud.email_to or 'el analista'}."
        )
    else:
        solicitud.email_to = None
        solicitud.email_cc = None
        solicitud.email_attach_report = False
        solicitud.email_skipped = True
        solicitud.email_error = None
        mensaje = "Solicitud enviada sin notificación por correo."

    solicitud.status = "notificada"
    solicitud.notified_at = utcnow()
    db.session.commit()
    registrar(
        "revision.enviar",
        f"review:{solicitud.id}",
        {
            "ok": True,
            "notificado": notificar,
            "destinatario": solicitud.email_to or "",
            "cc": solicitud.email_cc or "",
            "adjunto": bool(solicitud.email_attach_report),
            "estado": solicitud.status,
        },
        user_id=current_user.id,
    )
    flash(mensaje, "success")
    return redirect(_volver(solicitud))


@revisiones_bp.post("/<int:request_id>/descartar")
@login_required
@permiso_requerido("revisiones.ver")
def descartar(request_id: int):
    """Descarta un borrador y libera sus eventos."""
    solicitud = _solicitud(request_id)
    if not _puede_descartar_borrador(solicitud):
        abort(403)
    job_id = solicitud.job_id
    source_id = solicitud.source_id
    eventos = [evento.event_id for evento in solicitud.events]
    _borrar_archivos(solicitud, request_id)
    db.session.delete(solicitud)
    db.session.commit()
    registrar(
        "revision.descartar",
        f"review:{request_id}",
        {
            "job": job_id,
            "fuente": source_id,
            "eventos": eventos,
        },
        user_id=current_user.id,
    )
    flash(
        "Borrador descartado. Los eventos quedaron disponibles.",
        "success",
    )
    return redirect(url_for("revisiones.index"))


@revisiones_bp.post("/<int:request_id>/eliminar")
@login_required
@permiso_requerido("revisiones.eliminar")
def eliminar(request_id: int):
    """Elimina una solicitud, sus eventos y sus archivos asociados."""
    solicitud = _solicitud(request_id)
    job_id = solicitud.job_id
    source_id = solicitud.source_id
    eventos = [evento.event_id for evento in solicitud.events]
    _borrar_archivos(solicitud, request_id)
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
        as_attachment=not bool(request.args.get("inline")),
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
