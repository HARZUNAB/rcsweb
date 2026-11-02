"""Solicitudes de catálogos desde el servidor."""

from __future__ import annotations

from datetime import UTC, datetime, time

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from ..domain.catalogs import manifest as fuentes_manifest
from ..extensions import db
from ..forms import ReintentarForm, SolicitudForm
from ..models import CatalogRequest, CatalogRequestFile, Job, nuevo_uuid
from ..security import (
    alcance_total,
    permiso_requerido,
    puede_ver_solicitud,
)
from ..services.acquisition import (
    log_solicitud,
    preparar_workspace,
    reintentar_solicitud,
)
from ..services.audit import registrar
from ..services.queue import encolar_solicitud
from ..services.seiscomp import probar_conexion
from ..services.source_selection import (
    error_en,
    leer_formulario,
    opciones_formulario,
)

solicitudes_bp = Blueprint("solicitudes", __name__, url_prefix="/solicitudes")


def seiscomp_configurada() -> bool:
    from ..services.seiscomp import configurada

    return configurada()


def _solicitud(request_id: str) -> CatalogRequest:
    solicitud = db.session.get(CatalogRequest, request_id)
    if solicitud is None:
        abort(404)
    if not puede_ver_solicitud(solicitud, current_user):
        abort(403)
    return solicitud


def _job_de(solicitud: CatalogRequest) -> Job | None:
    return db.session.execute(
        db.select(Job).filter_by(catalog_request_id=solicitud.id)
    ).scalar_one_or_none()


def _puede_reintentar(solicitud: CatalogRequest) -> bool:
    if solicitud.status not in ("failed", "partial"):
        return False
    if _job_de(solicitud) is not None:
        return False
    if alcance_total(current_user):
        return True
    return solicitud.requested_by_id == getattr(current_user, "id", None)


@solicitudes_bp.get("/")
@login_required
@permiso_requerido("solicitudes.ver")
def lista():
    consulta = db.select(CatalogRequest).order_by(
        CatalogRequest.created_at.desc()
    )
    if not alcance_total(current_user):
        consulta = consulta.where(
            CatalogRequest.requested_by_id == current_user.id
        )
    solicitudes = (
        db.session.execute(consulta.limit(50)).scalars().all()
    )
    return render_template("solicitudes/list.html", solicitudes=solicitudes)


@solicitudes_bp.route("/nueva", methods=["GET", "POST"])
@login_required
@permiso_requerido("solicitudes.crear")
def nueva():
    referencia = fuentes_manifest.referencia()
    descargables = fuentes_manifest.descargables()
    seiscomp_ok = seiscomp_configurada()
    fuente_conexion = next(
        (fuente for fuente in descargables if fuente.availability == "seiscomp"),
        None,
    )

    def disponible(fuente) -> bool:
        if fuente.availability == "seiscomp":
            return seiscomp_ok
        return True

    form = SolicitudForm()
    form.primary_source.choices = [
        (fuente.id, fuente.label) for fuente in descargables
    ]
    if request.method == "GET":
        candidatas = [fuente for fuente in descargables if disponible(fuente)]
        predeterminada = fuentes_manifest.default_primary()
        elegida = next(
            (fuente for fuente in candidatas if fuente.id == predeterminada),
            candidatas[0] if candidatas else None,
        )
        form.primary_source.data = elegida.id if elegida else ""
        fuentes_form = opciones_formulario(
            descargables, {elegida.id} if elegida else set()
        )
    else:
        fuentes_form = leer_formulario(descargables)

    if request.method == "POST" and not (request.form.get("primary_source") or "").strip():
        predeterminada = fuentes_manifest.default_primary()
        form.primary_source.data = (
            predeterminada
            or (descargables[0].id if descargables else "")
        )

    if form.validate_on_submit():
        seleccionadas = [
            opcion for opcion in fuentes_form if opcion["incluir"]
        ]
        valido = True
        if not seleccionadas:
            error_en(
                fuentes_form,
                descargables[0],
                "Seleccione al menos una fuente local para descargar.",
            )
            valido = False
        for opcion in seleccionadas:
            fuente_def = opcion["fuente"]
            if fuente_def.availability == "seiscomp" and not seiscomp_ok:
                error_en(
                    fuentes_form,
                    fuente_def,
                    f"{fuente_def.label} no está configurado. Avise al administrador.",
                )
                valido = False
            if fuente_def.requires_radius and form.radio_km.data is None:
                error_en(
                    fuentes_form,
                    fuente_def,
                    "Indique el radio de estaciones.",
                )
                valido = False
        if seleccionadas:
            ids = {opcion["fuente"].id for opcion in seleccionadas}
            principal = form.primary_source.data
            if principal not in ids:
                form.primary_source.errors.append(
                    "La fuente principal debe estar entre las fuentes incluidas."
                )
                valido = False
        else:
            principal = ""

        if valido:
            inicio = form.period_start.data
            fin = form.period_end.data
            requiere_radio = any(
                opcion["fuente"].requires_radius for opcion in seleccionadas
            )
            radio_km = form.radio_km.data if requiere_radio else None
            solicitud = CatalogRequest(
                id=nuevo_uuid(),
                mode="ssh",
                period_start=datetime.combine(inicio, time.min, tzinfo=UTC),
                period_end=datetime.combine(fin, time(23, 59, 59), tzinfo=UTC),
                status="queued",
                progress=0,
                current_step="En cola",
                primary_source=principal,
                station_radius_km=radio_km,
                requested_by_id=current_user.id,
                server=form.server.data.strip(),
                remote_user=form.remote_user.data.strip(),
            )
            db.session.add(solicitud)
            db.session.commit()

            archivos = [
                CatalogRequestFile(
                    request_id=solicitud.id,
                    kind=referencia.id,
                    format=referencia.format,
                    display_name=referencia.label,
                    status="pending",
                )
            ]
            for opcion in seleccionadas:
                fuente_def = opcion["fuente"]
                archivos.append(
                    CatalogRequestFile(
                        request_id=solicitud.id,
                        kind=fuente_def.id,
                        format=fuente_def.format,
                        display_name=opcion["alias"] or fuente_def.label,
                        status="pending",
                    )
                )
            db.session.add_all(archivos)
            db.session.commit()
            preparar_workspace(solicitud.id)

            registrar(
                "catalog.request",
                entity=solicitud.id,
                meta={
                    "inicio": solicitud.inicio14,
                    "fin": solicitud.fin14,
                    "servidor": solicitud.server,
                    "usuario": solicitud.remote_user,
                    "catalogos": [referencia.id]
                    + [opcion["fuente"].id for opcion in seleccionadas],
                    "principal": principal,
                    "radio_km": radio_km,
                },
            )
            try:
                encolar_solicitud(solicitud.id, form.password.data)
                flash(
                    "Solicitud encolada. La descarga se actualiza automáticamente.",
                    "success",
                )
            except Exception as exc:  # noqa: BLE001
                solicitud.status = "failed"
                solicitud.error = f"No se pudo encolar: {exc}"
                solicitud.current_step = "Error al encolar"
                db.session.commit()
                flash(
                    "La solicitud quedó creada pero no se pudo encolar.",
                    "danger",
                )
            return redirect(
                url_for("solicitudes.detalle", request_id=solicitud.id)
            )

    return render_template(
        "solicitudes/new.html",
        form=form,
        fuentes=fuentes_form,
        seiscomp_ok=seiscomp_ok,
        fuente_conexion=fuente_conexion,
        radio_disponible=any(fuente.requires_radius for fuente in descargables),
        referencia=referencia,
    )


@solicitudes_bp.post("/probar-seiscomp")
@login_required
@permiso_requerido("solicitudes.crear")
def probar_seiscomp():
    resultado = probar_conexion()
    if resultado["ok"]:
        current_app.logger.info("SeisComp: bases visibles %s", resultado["bases"])
        flash("Conexión SeisComp OK.", "success")
    else:
        flash(f"No se pudo conectar a SeisComp: {resultado['error']}", "danger")
    return redirect(url_for("solicitudes.nueva"))


@solicitudes_bp.get("/<request_id>")
@login_required
@permiso_requerido("solicitudes.ver")
def detalle(request_id: str):
    return render_template("solicitudes/detail.html", **_contexto(request_id))


@solicitudes_bp.get("/<request_id>/estado")
@login_required
@permiso_requerido("solicitudes.ver")
def estado(request_id: str):
    return render_template("solicitudes/_page.html", **_contexto(request_id))


def _contexto(request_id: str) -> dict:
    solicitud = _solicitud(request_id)
    return {
        "solicitud": solicitud,
        "job": _job_de(solicitud),
        "log": log_solicitud(solicitud.id),
        "etiquetas": fuentes_manifest.etiquetas(),
        "form_reintento": ReintentarForm(),
        "puede_reintentar": _puede_reintentar(solicitud),
        "activa": solicitud.status in ("queued", "running"),
    }


@solicitudes_bp.post("/<request_id>/reintentar")
@login_required
@permiso_requerido("solicitudes.gestionar")
def reintentar(request_id: str):
    solicitud = _solicitud(request_id)
    if not _puede_reintentar(solicitud):
        abort(403)
    form = ReintentarForm()
    if not form.validate_on_submit():
        flash("Ingrese la contraseña del servidor para reintentar.", "warning")
        return redirect(url_for("solicitudes.detalle", request_id=solicitud.id))

    reintentar_solicitud(solicitud.id, form.password.data)
    registrar(
        "catalog.retry",
        entity=solicitud.id,
        meta={"servidor": solicitud.server, "usuario": solicitud.remote_user},
    )
    try:
        encolar_solicitud(solicitud.id, form.password.data)
        flash("Reintento encolado.", "success")
    except Exception as exc:  # noqa: BLE001
        solicitud.status = "failed"
        solicitud.error = f"No se pudo encolar el reintento: {exc}"
        db.session.commit()
        flash("No se pudo encolar el reintento.", "danger")
    return redirect(url_for("solicitudes.detalle", request_id=solicitud.id))
