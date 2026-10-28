"""Operaciones sobre trabajos (eliminación segura)."""

from __future__ import annotations

import shutil

from flask import current_app

from ..extensions import db
from ..models import Job
from .audit import registrar
from .workspace import ruta_workspace

ESTADOS_ELIMINABLES = ("draft", "done", "failed", "cancelled")


class JobNoEliminable(Exception):
    """El trabajo está activo o no existe."""


def puede_eliminar(job: Job, usuario) -> bool:
    """Admin o el creador del trabajo."""
    if usuario is None or not getattr(usuario, "is_authenticated", False):
        return False
    if getattr(usuario, "role", None) == "admin":
        return True
    return job.created_by_id == getattr(usuario, "id", None)


def eliminar_trabajo(job: Job, *, origen: str = "web", user_id: int | None = None) -> str:
    """Borra el trabajo, sus hijos y su workspace. La auditoría se conserva."""
    if job.status not in ESTADOS_ELIMINABLES:
        raise JobNoEliminable(
            "El trabajo está en cola o en ejecución. Cancelalo antes de eliminarlo."
        )

    job_id = job.id
    periodo = (job.inicio14, job.fin14)
    estado = job.status
    workspace = ruta_workspace(job_id)

    registrar(
        "job.delete",
        entity=job_id,
        meta={"periodo": periodo, "estado": estado, "origen": origen},
        user_id=user_id or job.created_by_id,
        commit=False,
    )
    db.session.delete(job)
    db.session.commit()

    try:
        shutil.rmtree(workspace, ignore_errors=True)
    except OSError:
        current_app.logger.warning("No se pudo borrar el workspace %s", workspace)

    return job_id
