"""Solicitudes de catálogos por SSH/SCP."""

from __future__ import annotations

from datetime import UTC, datetime, time

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..forms import ReintentarForm, SolicitudForm
from ..models import CatalogRequest, CatalogRequestFile, Job, nuevo_uuid
from ..services.acquisition import (
    log_solicitud,
    preparar_workspace,
    reintentar_solicitud,
)
from ..services.audit import registrar
from ..services.queue import encolar_solicitud
from ..services.sources import etiquetas

solicitudes_bp = Blueprint("solicitudes", __name__, url_prefix="/solicitudes")


def _solicitud(request_id: str) -> CatalogRequest:
    solicitud = db.session.get(CatalogRequest, request_id)
    if solicitud is None:
        abort(404)
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
    if getattr(current_user, "role", None) == "admin":
        return True
    return solicitud.requested_by_id == getattr(current_user, "id", None)


@solicitudes_bp.get("/")
@login_required
def lista():
    solicitudes = (
        db.session.execute(
            db.select(CatalogRequest).order_by(CatalogRequest.created_at.desc()).limit(50)
        )
        .scalars()
        .all()
    )
    return render_template("solicitudes/list.html", solicitudes=solicitudes)


@solicitudes_bp.route("/nueva", methods=["GET", "POST"])
@login_required
def nueva():
    form = SolicitudForm()
    if form.validate_on_submit():
        inicio = form.period_start.data
        fin = form.period_end.data
        solicitud = CatalogRequest(
            id=nuevo_uuid(),
            mode="ssh",
            period_start=datetime.combine(inicio, time.min, tzinfo=UTC),
            period_end=datetime.combine(fin, time(23, 59, 59), tzinfo=UTC),
            status="queued",
            progress=0,
            current_step="En cola",
            requested_by_id=current_user.id,
            server=form.server.data.strip(),
            remote_user=form.remote_user.data.strip(),
        )
        db.session.add(solicitud)
        db.session.commit()
        db.session.add_all(
            [
                CatalogRequestFile(
                    request_id=solicitud.id,
                    kind="eventquery",
                    format="eventquery",
                    status="pending",
                ),
                CatalogRequestFile(
                    request_id=solicitud.id,
                    kind="seisan",
                    format="seisan",
                    status="pending",
                ),
            ]
        )
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
                "catalogos": ["eventquery", "seisan"],
            },
        )
        try:
            encolar_solicitud(solicitud.id, form.password.data)
            flash("Solicitud encolada. La descarga se actualiza automáticamente.", "success")
        except Exception as exc:  # noqa: BLE001
            solicitud.status = "failed"
            solicitud.error = f"No se pudo encolar: {exc}"
            solicitud.current_step = "Error al encolar"
            db.session.commit()
            flash("La solicitud quedó creada pero no se pudo encolar.", "danger")
        return redirect(url_for("solicitudes.detalle", request_id=solicitud.id))
    return render_template("solicitudes/new.html", form=form)


@solicitudes_bp.get("/<request_id>")
@login_required
def detalle(request_id: str):
    return render_template("solicitudes/detail.html", **_contexto(request_id))


@solicitudes_bp.get("/<request_id>/estado")
@login_required
def estado(request_id: str):
    return render_template("solicitudes/_page.html", **_contexto(request_id))


def _contexto(request_id: str) -> dict:
    solicitud = _solicitud(request_id)
    return {
        "solicitud": solicitud,
        "job": _job_de(solicitud),
        "log": log_solicitud(solicitud.id),
        "etiquetas": etiquetas(),
        "form_reintento": ReintentarForm(),
        "puede_reintentar": _puede_reintentar(solicitud),
        "activa": solicitud.status in ("queued", "running"),
    }


@solicitudes_bp.post("/<request_id>/reintentar")
@login_required
def reintentar(request_id: str):
    solicitud = _solicitud(request_id)
    if not _puede_reintentar(solicitud):
        abort(403)
    form = ReintentarForm()
    if not form.validate_on_submit():
        flash("Ingresá la contraseña SSH para reintentar.", "warning")
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
