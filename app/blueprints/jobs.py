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
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required

from ..extensions import db
from ..forms import JobForm
from ..models import Job, JobArtifact, JobFile, JobSource, nuevo_uuid
from ..services.audit import registrar
from ..services.jobs import JobNoEliminable, eliminar_trabajo, puede_eliminar
from ..services.queue import encolar_trabajo
from ..services.results import cargar_indice
from ..services.sources import default_primary, etiquetas
from ..services.validators import validar_fuente
from ..services.workspace import (
    crear_workspace,
    guardar_archivo,
    leer_log,
    nombre_entrada,
    ruta_workspace,
)

jobs_bp = Blueprint("jobs", __name__, url_prefix="/jobs")


def _job(job_id: str) -> Job:
    job = db.session.get(Job, job_id)
    if job is None:
        abort(404)
    return job


def _contexto_detalle(job: Job) -> dict:
    workspace = ruta_workspace(job.id)
    indice = cargar_indice(workspace)
    codigos = set(indice.get("no_publicados", {})) | set(indice.get("no_actualizados", {}))
    for clave in indice.get("repetidos", {}):
        if not clave.startswith("publica"):
            codigos.add(clave.split("_", 1)[0])
    fuentes = sorted(
        codigos,
        key=lambda codigo: (0 if codigo == default_primary() else 1, codigo),
    )
    return {
        "job": job,
        "indice": indice,
        "log": leer_log(workspace, max_lineas=250),
        "artefactos": job.artifacts,
        "activo": job.activo,
        "etiquetas": etiquetas(),
        "fuentes": fuentes,
    }


@jobs_bp.route("/new", methods=["GET", "POST"])
@login_required
def nuevo():
    form = JobForm()
    if request.method == "GET":
        form.incluir_seiscomp.data = True
        form.incluir_seisan.data = False
        form.primary_source.data = default_primary()

    if form.validate_on_submit():
        inicio = form.period_start.data
        fin = form.period_end.data
        period_start = datetime.combine(inicio, time.min, tzinfo=UTC)
        period_end = datetime.combine(fin, time(23, 59, 59), tzinfo=UTC)

        seleccion = []
        if form.incluir_seiscomp.data:
            seleccion.append("seiscomp")
        if form.incluir_seisan.data:
            seleccion.append("seisan")

        principal = form.primary_source.data
        if principal not in seleccion:
            predeterminada = default_primary()
            principal = predeterminada if predeterminada in seleccion else seleccion[0]
        orden = [principal] + [codigo for codigo in seleccion if codigo != principal]

        job = Job(
            id=nuevo_uuid(),
            period_start=period_start,
            period_end=period_end,
            status="draft",
            origin="upload",
            current_step="Validando catálogos",
            created_by_id=current_user.id,
        )
        workspace = crear_workspace(job.id)
        archivos_meta = []
        rutas = {}

        def _guardar(kind: str, archivo) -> None:
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
            rutas[kind] = destino

        try:
            _guardar("eventquery", form.eventquery.data)
            for codigo in orden:
                archivo = getattr(form, codigo).data
                if archivo is None or not archivo.filename:
                    raise ValueError(f"Falta el archivo de {codigo}.")
                _guardar(codigo, archivo)

            db.session.add(job)
            db.session.add(JobSource(job_id=job.id, kind="eventquery", role="referencia"))
            for codigo in orden:
                db.session.add(
                    JobSource(
                        job_id=job.id,
                        kind=codigo,
                        role=("local_principal" if codigo == principal else "local_secundaria"),
                    )
                )
            db.session.commit()
        except Exception as exc:  # noqa: BLE001 - se informa al usuario
            db.session.rollback()
            shutil.rmtree(workspace, ignore_errors=True)
            flash(f"No se pudo crear el trabajo: {exc}", "danger")
            return render_template("jobs/new.html", form=form)

        # Validación de contenido, formato y cobertura.
        try:
            validaciones = {}
            for source in job.sources:
                ruta = rutas.get(source.kind)
                if ruta is None:
                    resultado = {
                        "ok": False,
                        "errores": ["No se encontró el archivo cargado."],
                        "advertencias": [],
                        "eventos": 0,
                    }
                else:
                    resultado = validar_fuente(source.kind, ruta, job.period_start, job.period_end)
                validaciones[source.kind] = resultado
                source.status = "ok" if resultado["ok"] else "error"
                mensajes = resultado["errores"] + resultado["advertencias"]
                source.message = "\n".join(mensajes) if mensajes else None
            db.session.commit()
        except Exception as exc:  # noqa: BLE001
            job.status = "failed"
            job.error = f"No se pudo validar los catálogos: {exc}"
            job.current_step = "Error de validación"
            db.session.commit()
            flash("No se pudo validar los catálogos. Revisá el detalle.", "danger")
            return redirect(url_for("jobs.detalle", job_id=job.id))

        todo_ok = all(resultado["ok"] for resultado in validaciones.values())
        meta = {
            "inicio": job.inicio14,
            "fin": job.fin14,
            "fuentes": orden,
            "principal": principal,
            "archivos": archivos_meta,
            "validacion": {
                codigo: {
                    "ok": resultado["ok"],
                    "eventos": resultado["eventos"],
                    "errores": resultado["errores"],
                }
                for codigo, resultado in validaciones.items()
            },
        }

        if not todo_ok:
            job.status = "draft"
            job.current_step = "Validación fallida"
            job.error = (
                "Alguno de los catálogos no pasó la validación. "
                "Revisá el detalle, corregí el archivo y creá un trabajo nuevo."
            )
            db.session.commit()
            registrar("job.create", entity=job.id, meta=meta)
            flash(
                "El trabajo quedó en borrador: hay catálogos inválidos. "
                "Revisá el detalle antes de volver a intentar.",
                "danger",
            )
            return redirect(url_for("jobs.detalle", job_id=job.id))

        job.status = "queued"
        job.current_step = "En cola"
        job.error = None
        db.session.commit()
        registrar("job.create", entity=job.id, meta=meta)

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
