"""Operaciones sobre trabajos (eliminación segura)."""

from __future__ import annotations

import shutil

from flask import current_app

from ..extensions import db
from ..models import CatalogRequest, Job, utcnow
from ..security import alcance_total
from .audit import registrar
from .workspace import ruta_workspace

ESTADOS_ELIMINABLES = ("draft", "done", "failed", "cancelled")


class JobNoEliminable(Exception):
    """El trabajo está activo o no existe."""


def puede_eliminar(job: Job, usuario) -> bool:
    """Admin o el creador del trabajo."""
    if usuario is None or not getattr(usuario, "is_authenticated", False):
        return False
    if alcance_total(usuario):
        return True
    return job.created_by_id == getattr(usuario, "id", None)


def _respaldar_senal(workspace) -> None:
    """Guarda en la base los resultados de señal que solo están en el CSV."""
    resultados = workspace / "resultados"
    if not resultados.is_dir():
        return
    fuentes = sorted(
        {
            ruta.stem[len("revision_picks_") :]
            for ruta in resultados.glob("revision_picks_*.csv")
            if ruta.stem.startswith("revision_picks_")
        }
    )
    if not fuentes:
        return
    from . import picks_signal

    for fuente in fuentes:
        if not fuente:
            continue
        try:
            importados = picks_signal.importar_reporte(
                workspace,
                fuente,
                estricto=True,
            )
        except Exception as exc:  # noqa: BLE001 - no se debe perder el respaldo
            current_app.logger.exception(
                "No se pudo respaldar la señal del trabajo %s",
                workspace.name,
            )
            raise JobNoEliminable(
                "No se pudo respaldar el análisis de señal. "
                "El trabajo no se eliminó."
            ) from exc
        if importados:
            current_app.logger.info(
                "Respaldo de señal job=%s fuente=%s resultados=%s",
                workspace.name,
                fuente,
                importados,
            )


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
    if workspace.exists():
        _respaldar_senal(workspace)

    registrar(
        "job.delete",
        entity=job_id,
        meta={"periodo": periodo, "estado": estado, "origen": origen},
        user_id=user_id or job.created_by_id,
        commit=False,
    )
    if job.catalog_request_id:
        solicitud = db.session.get(CatalogRequest, job.catalog_request_id)
        if solicitud is not None:
            solicitud.job_deleted_at = utcnow()
    db.session.delete(job)
    db.session.commit()

    try:
        shutil.rmtree(workspace, ignore_errors=True)
    except OSError:
        current_app.logger.warning("No se pudo borrar el workspace %s", workspace)

    return job_id
