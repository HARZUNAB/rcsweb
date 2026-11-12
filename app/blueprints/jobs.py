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

from ..domain.catalogs import manifest as fuentes_manifest
from ..domain.catalogs.registry import adaptador as obtener_adaptador
from ..extensions import db
from ..forms import JobForm
from ..models import Job, JobArtifact, JobFile, JobSource, nuevo_uuid
from ..security import permiso_requerido, puede_ver_trabajo
from ..services import indicios
from ..services.audit import registrar
from ..services.jobs import JobNoEliminable, eliminar_trabajo, puede_eliminar
from ..services.panels import datasets_disponibles
from ..services.queue import encolar_trabajo
from ..services.results import cargar_indice
from ..services.source_selection import (
    error_en,
    extension_permitida,
    fuente_por_id,
    leer_formulario,
    opciones_formulario,
)
from ..services.source_status import validar_fuentes_directas
from ..services.sources import disponibilidad_fuentes
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
    if not puede_ver_trabajo(job, current_user):
        abort(403)
    return job


def _contexto_detalle(job: Job) -> dict:
    if job.status in ("done", "failed"):
        validar_fuentes_directas(job)
    workspace = ruta_workspace(job.id)
    indice = cargar_indice(workspace)
    codigos = set(indice.get("no_publicados", {})) | set(indice.get("no_actualizados", {}))
    referencia = fuentes_manifest.referencia()
    for clave in indice.get("repetidos", {}):
        if not (
            clave == referencia.id
            or clave.startswith(referencia.id + "_")
            or clave.startswith("publica")
        ):
            codigos.add(clave.split("_", 1)[0])
    fuentes = sorted(
        codigos,
        key=lambda codigo: (
            0 if codigo == fuentes_manifest.default_primary() else 1,
            codigo,
        ),
    )
    return {
        "job": job,
        "indice": indice,
        "indicios": indicios.leer_resumen(workspace),
        "log": leer_log(workspace, max_lineas=250),
        "artefactos": job.artifacts,
        "activo": job.activo,
        "etiquetas": fuentes_manifest.etiquetas(),
        "aliases": {source.kind: source.alias_mostrado for source in job.sources},
        "fuentes": fuentes,
        "paneles": datasets_disponibles(workspace),
    }


def _disponibilidad_fuentes(definiciones) -> dict:
    """Rango informativo de las fuentes que se consultan directamente."""
    return disponibilidad_fuentes(definiciones, current_user)


@jobs_bp.get("/new")
@login_required
def nuevo_redirige():
    """La entrada por defecto es solicitar los catálogos al servidor."""
    return redirect(url_for("solicitudes.nueva"))


@jobs_bp.route("/new/subir", methods=["GET", "POST"])
@login_required
@permiso_requerido("trabajos.crear")
def nuevo():
    definiciones = fuentes_manifest.fuentes()
    locales = fuentes_manifest.locales()
    referencia = fuentes_manifest.referencia()
    form = JobForm()
    form.primary_source.choices = [(fuente.id, fuente.label) for fuente in locales]

    if request.method == "GET":
        form.primary_source.data = (
            fuentes_manifest.default_primary()
            or (locales[0].id if locales else "")
        )
        fuentes_form = opciones_formulario(
            definiciones,
            {
                referencia.id,
                *(
                    fuente.id
                    for fuente in locales
                    if fuente.default_primary
                ),
            },
        )
    else:
        fuentes_form = leer_formulario(definiciones)
        referencia_form = fuente_por_id(fuentes_form, referencia.id)
        if referencia_form is not None:
            referencia_form["incluir"] = True

    if request.method == "POST" and not (request.form.get("primary_source") or "").strip():
        form.primary_source.data = (
            fuentes_manifest.default_primary()
            or (locales[0].id if locales else "")
        )

    disponibilidad = _disponibilidad_fuentes(definiciones)

    if form.validate_on_submit():
        seleccionadas = [
            opcion
            for opcion in fuentes_form
            if opcion["fuente"].es_local and opcion["incluir"]
        ]
        valido = True

        if not seleccionadas:
            error_en(
                fuentes_form,
                locales[0],
                "Seleccione al menos una fuente local para comparar con la referencia.",
            )
            valido = False

        for opcion in fuentes_form:
            fuente_def = opcion["fuente"]
            if not fuente_def.es_referencia and not opcion["incluir"]:
                continue
            if not extension_permitida(fuente_def, opcion["archivo"]):
                error_en(
                    fuentes_form,
                    fuente_def,
                    f"Seleccione un archivo válido para {fuente_def.label} "
                    f"({', '.join(fuente_def.accept) or 'sin extensión fija'}).",
                )
                valido = False

        if seleccionadas:
            ids = {opcion["fuente"].id for opcion in seleccionadas}
            principal = form.primary_source.data
            if principal not in ids:
                predeterminada = fuentes_manifest.default_primary()
                principal = (
                    predeterminada if predeterminada in ids else seleccionadas[0]["fuente"].id
                )
                form.primary_source.data = principal
        else:
            principal = ""

        if valido:
            inicio = form.period_start.data
            fin = form.period_end.data
            period_start = datetime.combine(inicio, time.min, tzinfo=UTC)
            period_end = datetime.combine(fin, time(23, 59, 59), tzinfo=UTC)
            orden = [principal] + [
                opcion["fuente"].id
                for opcion in seleccionadas
                if opcion["fuente"].id != principal
            ]
            opciones_por_id = {
                opcion["fuente"].id: opcion for opcion in fuentes_form
            }

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
                referencia_opcion = opciones_por_id[referencia.id]
                if referencia.requires_file:
                    _guardar(referencia.id, referencia_opcion["archivo"])
                for source_id in orden:
                    fuente_def = opciones_por_id[source_id]["fuente"]
                    if fuente_def.requires_file:
                        _guardar(
                            source_id,
                            opciones_por_id[source_id]["archivo"],
                        )

                db.session.add(job)
                db.session.add(
                    JobSource(
                        job_id=job.id,
                        kind=referencia.id,
                        alias=referencia.label,
                        format=referencia.format,
                        role="referencia",
                        priority=0,
                        capabilities=sorted(referencia.capacidades),
                    )
                )
                for indice, source_id in enumerate(orden, start=1):
                    opcion = opciones_por_id[source_id]
                    fuente_def = opcion["fuente"]
                    db.session.add(
                        JobSource(
                            job_id=job.id,
                            kind=fuente_def.id,
                            alias=opcion["alias"] or fuente_def.label,
                            format=fuente_def.format,
                            role=(
                                "local_principal"
                                if fuente_def.id == principal
                                else "local_secundaria"
                            ),
                            priority=indice,
                            capabilities=sorted(fuente_def.capacidades),
                        )
                    )
                db.session.commit()
            except Exception as exc:  # noqa: BLE001 - se informa al usuario
                db.session.rollback()
                shutil.rmtree(workspace, ignore_errors=True)
                flash(f"No se pudo crear el trabajo: {exc}", "danger")
                return render_template(
                    "jobs/new.html",
                    form=form,
                    fuentes=fuentes_form,
                    disponibilidad=disponibilidad,
                )

            try:
                validaciones = {}
                for source in job.sources:
                    definicion = fuentes_manifest.por_id(source.kind)
                    if definicion is not None and not definicion.requires_file:
                        adapter = obtener_adaptador(definicion.format)
                        adapter.source_id = definicion.id
                        resultado = adapter.validar_periodo(
                            job, disponibilidad.get(definicion.id)
                        )
                        if (
                            resultado.get("ok")
                            and resultado.get("eventos", 0) == 0
                            and len(seleccionadas) == 1
                        ):
                            resultado["ok"] = False
                            resultado["errores"] = list(
                                resultado.get("advertencias", [])
                            ) + [
                                f"{definicion.label} no tiene eventos en el "
                                "período seleccionado y es la única fuente "
                                "local. Ajuste las fechas o seleccione otra "
                                "fuente."
                            ]
                            resultado["advertencias"] = []
                    else:
                        ruta = rutas.get(source.kind)
                        validador = definicion.validator if definicion else source.kind
                        if ruta is None:
                            resultado = {
                                "ok": False,
                                "errores": ["No se encontró el archivo cargado."],
                                "advertencias": [],
                                "eventos": 0,
                            }
                        else:
                            resultado = validar_fuente(
                                validador,
                                ruta,
                                job.period_start,
                                job.period_end,
                            )
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
                flash("No se pudo validar los catálogos. Revise el detalle.", "danger")
                return redirect(url_for("jobs.detalle", job_id=job.id))

            todo_ok = all(resultado["ok"] for resultado in validaciones.values())
            meta = {
                "inicio": job.inicio14,
                "fin": job.fin14,
                "fuentes": orden,
                "principal": principal,
                "archivos": archivos_meta,
                "extracciones": {
                    fuente.id: fuente.nombre_extraccion(
                        job.inicio14, job.fin14
                    )
                    for fuente in definiciones
                    if not fuente.requires_file
                    and fuente.id in orden
                },
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
                    "Alguna fuente no pasó la validación. "
                    "Revise el detalle y cree un trabajo nuevo."
                )
                db.session.commit()
                registrar("job.create", entity=job.id, meta=meta)
                flash(
                    "El trabajo quedó en borrador: hay fuentes inválidas. "
                    "Revise el detalle antes de volver a intentar.",
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
                flash(
                    "Trabajo encolado. El progreso se actualiza automáticamente.",
                    "success",
                )
            except Exception as exc:  # noqa: BLE001 - Redis caído, por ejemplo
                job.status = "failed"
                job.error = f"No se pudo encolar en Celery: {exc}"
                job.current_step = "Error al encolar"
                db.session.commit()
                flash(
                    "El trabajo quedó creado pero no se pudo encolar. "
                    "Revise que Redis y el worker estén activos.",
                    "danger",
                )

            return redirect(url_for("jobs.detalle", job_id=job.id))

    return render_template(
        "jobs/new.html",
        form=form,
        fuentes=fuentes_form,
        disponibilidad=disponibilidad,
    )


@jobs_bp.get("/<job_id>")
@login_required
@permiso_requerido("trabajos.ver")
def detalle(job_id: str):
    return render_template("jobs/detail.html", **_contexto_detalle(_job(job_id)))


@jobs_bp.get("/<job_id>/estado")
@login_required
@permiso_requerido("trabajos.ver")
def estado(job_id: str):
    return render_template("jobs/_page.html", **_contexto_detalle(_job(job_id)))


@jobs_bp.post("/<job_id>/cancelar")
@login_required
@permiso_requerido("trabajos.cancelar")
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
@permiso_requerido("trabajos.eliminar")
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
@permiso_requerido("trabajos.descargar")
def descargas(job_id: str):
    job = _job(job_id)
    grupos = {
        "resultado": [a for a in job.artifacts if a.tipo == "resultado"],
        "entregable": [a for a in job.artifacts if a.tipo == "entregable"],
        "catalogo": [a for a in job.artifacts if a.tipo == "catalogo"],
    }
    return render_template(
        "jobs/downloads.html",
        job=job,
        grupos=grupos,
        indice=cargar_indice(ruta_workspace(job.id)),
        etiquetas=fuentes_manifest.etiquetas(),
        aliases={source.kind: source.alias_mostrado for source in job.sources},
    )


@jobs_bp.get("/<job_id>/descargar/<int:artifact_id>")
@login_required
@permiso_requerido("trabajos.descargar")
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
