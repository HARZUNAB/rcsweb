"""Panel principal."""

from __future__ import annotations

from flask import Blueprint, render_template
from flask_login import current_user, login_required
from sqlalchemy import func

from ..extensions import db
from ..models import Job
from ..security import alcance_total, permiso_requerido

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.get("/")
@login_required
@permiso_requerido("trabajos.ver")
def index():
    # Un analista o una consulta solo ven sus propios trabajos; el
    # administrador y el supervisor ven todo el sistema.
    ver_todos = alcance_total(current_user)
    consulta = db.select(Job).order_by(Job.created_at.desc()).limit(10)
    consulta_estado = db.select(Job.status, func.count(Job.id)).group_by(Job.status)
    if not ver_todos:
        consulta = consulta.where(Job.created_by_id == current_user.id)
        consulta_estado = consulta_estado.where(
            Job.created_by_id == current_user.id
        )
    trabajos = db.session.execute(consulta).scalars().all()
    por_estado = dict(db.session.execute(consulta_estado).all())

    stats = {
        "total": sum(por_estado.values()),
        "en_cola": por_estado.get("queued", 0),
        "en_curso": por_estado.get("running", 0),
        "terminados": por_estado.get("done", 0),
        "fallidos": por_estado.get("failed", 0),
    }

    return render_template("dashboard/index.html", trabajos=trabajos, stats=stats)
