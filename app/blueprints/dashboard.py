"""Panel principal."""

from __future__ import annotations

from flask import Blueprint, render_template
from flask_login import login_required
from sqlalchemy import func

from ..extensions import db
from ..models import Job

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.get("/")
@login_required
def index():
    trabajos = (
        db.session.execute(db.select(Job).order_by(Job.created_at.desc()).limit(10)).scalars().all()
    )

    por_estado = dict(
        db.session.execute(db.select(Job.status, func.count(Job.id)).group_by(Job.status)).all()
    )

    stats = {
        "total": sum(por_estado.values()),
        "en_cola": por_estado.get("queued", 0),
        "en_curso": por_estado.get("running", 0),
        "terminados": por_estado.get("done", 0),
        "fallidos": por_estado.get("failed", 0),
    }

    return render_template("dashboard/index.html", trabajos=trabajos, stats=stats)
