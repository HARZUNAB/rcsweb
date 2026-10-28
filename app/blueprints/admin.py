"""Administración: auditoría de acciones."""

from __future__ import annotations

import datetime

from flask import Blueprint, render_template, request
from sqlalchemy import func

from ..extensions import db
from ..models import AuditLog, User
from ..security import admin_required

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

PER_PAGE = 50


def _fecha(texto: str, fin: bool = False):
    try:
        valor = datetime.datetime.strptime(texto, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    hora = datetime.time(23, 59, 59) if fin else datetime.time.min
    return datetime.datetime.combine(valor, hora, tzinfo=datetime.UTC)


@admin_bp.get("/auditoria")
@admin_required
def auditoria():
    accion = request.args.get("accion", "").strip()
    usuario = request.args.get("usuario", "").strip()
    desde = request.args.get("desde", "").strip()
    hasta = request.args.get("hasta", "").strip()
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1

    consulta = db.select(AuditLog)
    if accion:
        consulta = consulta.where(AuditLog.action == accion)
    if usuario:
        encontrado = db.session.execute(
            db.select(User).filter_by(username=usuario)
        ).scalar_one_or_none()
        consulta = consulta.where(AuditLog.user_id == (encontrado.id if encontrado else -1))
    fecha_desde = _fecha(desde)
    fecha_hasta = _fecha(hasta, fin=True)
    if fecha_desde is not None:
        consulta = consulta.where(AuditLog.created_at >= fecha_desde)
    if fecha_hasta is not None:
        consulta = consulta.where(AuditLog.created_at <= fecha_hasta)

    consulta = consulta.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    paginacion = db.paginate(consulta, page=page, per_page=PER_PAGE, error_out=False)

    acciones = (
        db.session.execute(db.select(AuditLog.action).distinct().order_by(AuditLog.action))
        .scalars()
        .all()
    )
    total = db.session.execute(db.select(func.count()).select_from(AuditLog)).scalar_one()

    return render_template(
        "admin/audit.html",
        paginacion=paginacion,
        acciones=acciones,
        total=total,
        accion=accion,
        usuario=usuario,
        desde=desde,
        hasta=hasta,
    )
