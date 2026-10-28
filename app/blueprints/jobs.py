"""Alta, seguimiento y descargas de trabajos."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime, time
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    send_file,
    url_for,
)
from flask_login import current_user, login_required

from ..extensions import db
from ..forms import JobForm
from ..models import Job, JobArtifact, JobFile, nuevo_uuid
from ..services.audit import registrar
from ..services.jobs import JobNoEliminable, eliminar_trabajo, puede_eliminar
from ..services.queue import encolar_trabajo
from ..services.results import cargar_indice
from ..services.workspace import (
    crear_workspace,
    guardar_archivo,
    leer_log,
    nombre_entrada,
    ruta_workspace,
)

jobs_bp = Blueprint("jobs", __name__, url_prefix="/jobs")

KINDS = (
    ("seisan", "seisan"),
    ("eventquery", "eventquery"),
    ("seiscomp", "seiscomp"),
)


def _job(job_id: str) -> Job:
    job = db.session.get(Job, job_id)
    if job is None:
        abort(404)
    return job


def _contexto_detalle(job: Job) -> dict:
    workspace = ruta_workspace(job.id)
    return {
        "job": job,
        "indice": cargar_indice(workspace),
        "log": leer_log(workspace, max_lineas=250),
        "artefactos": job.artifacts,
        "activo": job.activo,
    }


@jobs_bp.route("/new", methods=["GET", "POST"])
@login_required
def nuevo():
    form = JobForm()

    if form.validate_on_submit():
        inicio = form.period_start.data
        fin = form.period_end.data
        period_start = datetime.combine(inicio, time.min, tzinfo=UTC)
        period_end = datetime.combine(fin, time(23, 59, 59), tzinfo=UTC)

        job = Job(
            id=nuevo_uuid(),
            period_start=period_start,
            period_end=period_end,
            status="draft",
            created_by_id=current_user.id,
        )
        workspace = crear_workspace(job.id)
        archivos_meta = []

        try:
            for kind, campo in KINDS:
                archivo = getattr(form, campo).data
                if not archivo or not archivo.filename:
                    continue

                almacenado = nombre_entrada(kind, archivo.filename)
                destino = workspace / "inputs" / almacenado
                tamano, sha256 = guardar_archivo(archivo, destino)
                if tamano == 0:
                    raise ValueError(f"El archivo «{archivo.filename}» está vacío.")

                db.session.add(
                    JobFile(
                        job_id=job.id,
                        kind=kind,
                        original_name=archivo.filename,
                        stored_name=f"inputs/{almacenado}",
                        size=tamano,
                        sha256=sha256,
                    )
                )
                archivos_meta.append(
                    {
                        "kind": kind,
                        "nombre": archivo.filename,
                        "bytes": tamano,
                        "sha256": sha256,
                    }
                )

            job.status = "queued"
            db.session.add(job)
            db.session.commit()
            registrar(
                "job.create",
                entity=job.id,
                meta={
                    "inicio": job.inicio14,
                    "fin": job.fin14,
                    "archivos": archivos_meta,
                },
            )
        except Exception as exc:  # noqa: BLE001 - se informa al usuario
            db.session.rollback()
            shutil.rmtree(workspace, ignore_errors=True)
            flash(f"No se pudo crear el trabajo: {exc}", "danger")
            return render_template("jobs/new.html", form=form)

        try:
            encolar_trabajo(job.id)
            flash("Trabajo encolado. El progreso se actualiza automáticamente.", "success")
        except Exception as exc:  # noqa: BLE001 - Redis caído, por ejemplo
            job.status = "failed"
            job.error = f"No se pudo encolar en Celery: {exc}"
            job.current_step = "Error al encolar"
            db.session.commit()
            flash(
                "El trabajo quedó creado pero no se pudo encolar. "
                "Revisa que Redis y el worker estén activos.",
                "danger",
            )

        return redirect(url_for("jobs.detalle", job_id=job.id))

    return render_template("jobs/new.html", form=form)


@jobs_bp.get("/<job_id>")
@login_required
def detalle(job_id: str):
    return render_template("jobs/detail.html", **_contexto_detalle(_job(job_id)))


@jobs_bp.get("/<job_id>/estado")
@login_required
def estado(job_id: str):
    return render_template("jobs/_page.html", **_contexto_detalle(_job(job_id)))


@jobs_bp.post("/<job_id>/cancelar")
@login_required
def cancelar(job_id: str):
    job = _job(job_id)
    if job.status == "queued":
        job.status = "cancelled"
        job.current_step = "Cancelado"
        job.finished_at = datetime.now(UTC)
        db.session.commit()
        registrar("job.cancel", entity=job.id, meta={"estado_previo": "queued"})
        flash("Trabajo cancelado antes de comenzar.", "info")
    elif job.status == "running":
        job.status = "cancelling"
        job.current_step = "Cancelando…"
        db.session.commit()
        registrar("job.cancel", entity=job.id, meta={"estado_previo": "running"})
        flash("Se solicitó cancelar el trabajo.", "warning")
    else:
        flash("El trabajo ya terminó; no hay nada que cancelar.", "info")
    return redirect(url_for("jobs.detalle", job_id=job.id))


@jobs_bp.post("/<job_id>/eliminar")
@login_required
def eliminar(job_id: str):
    job = _job(job_id)
    if not puede_eliminar(job, current_user):
        abort(403)
    try:
        eliminar_trabajo(job, user_id=current_user.id)
    except JobNoEliminable as exc:
        flash(str(exc), "warning")
        return redirect(url_for("jobs.detalle", job_id=job.id))
    flash("Trabajo eliminado junto con sus resultados y archivos.", "success")
    return redirect(url_for("dashboard.index"))


@jobs_bp.get("/<job_id>/descargas")
@login_required
def descargas(job_id: str):
    job = _job(job_id)
    grupos = {
        "resultado": [a for a in job.artifacts if a.tipo == "resultado"],
        "entregable": [a for a in job.artifacts if a.tipo == "entregable"],
        "catalogo": [a for a in job.artifacts if a.tipo == "catalogo"],
    }
    return render_template("jobs/downloads.html", job=job, grupos=grupos)


@jobs_bp.get("/<job_id>/descargar/<int:artifact_id>")
@login_required
def descargar(job_id: str, artifact_id: int):
    job = _job(job_id)
    artefacto = db.session.get(JobArtifact, artifact_id)
    if artefacto is None or artefacto.job_id != job.id:
        abort(404)

    workspace = ruta_workspace(job.id).resolve()
    ruta = (workspace / artefacto.ruta).resolve()
    if not ruta.is_file() or not ruta.is_relative_to(workspace):
        abort(404)

    registrar(
        "download",
        entity=artefacto.ruta,
        meta={"job": job.id, "bytes": artefacto.size},
    )
    return send_file(
        ruta,
        as_attachment=True,
        download_name=Path(artefacto.ruta).name,
        mimetype=artefacto.mime or "application/octet-stream",
    )
