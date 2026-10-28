"""Tareas del pipeline.

En la etapa 0 solo hay un *ping* y un esqueleto de ``run_job``. La etapa 1
conectará ``run_job`` con ``app.services.pipeline``.
"""

from __future__ import annotations

import logging

from .celery_app import celery

log = logging.getLogger(__name__)


@celery.task(name="tasks.ping")
def ping() -> dict:
    return {"pong": True}


@celery.task(name="tasks.run_job", bind=True)
def run_job(self, job_id: str) -> dict:
    """Placeholder: la orquestación real llega en la etapa 1."""
    log.info("run_job job_id=%s (stub de etapa 0)", job_id)
    return {"job_id": job_id, "status": "stub"}
