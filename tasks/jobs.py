"""Tareas del pipeline."""

from __future__ import annotations

import logging

from .celery_app import celery

log = logging.getLogger(__name__)


@celery.task(name="tasks.ping")
def ping() -> dict:
    return {"pong": True}


@celery.task(name="tasks.run_job", bind=True)
def run_job(self, job_id: str) -> dict:
    """Ejecuta el pipeline completo de un trabajo."""
    from app import create_app
    from app.extensions import db
    from app.models import Job

    aplicacion = create_app()
    with aplicacion.app_context():
        log.info("run_job job_id=%s", job_id)
        try:
            from app.services.pipeline import ejecutar_pipeline

            return ejecutar_pipeline(job_id)
        except Exception as exc:  # noqa: BLE001 - deja rastro en la base
            job = db.session.get(Job, job_id)
            if job is not None and job.status in ("queued", "running", "cancelling"):
                job.status = "failed"
                job.error = f"Error interno del worker: {exc}"
                job.current_step = "Error"
                db.session.commit()
            raise
