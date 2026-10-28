"""Encolado de trabajos en Celery.

Se aísla en un módulo para poder sustituirlo en los tests sin levantar Redis.
"""

from __future__ import annotations


def encolar_trabajo(job_id: str):
    from tasks.jobs import run_job

    return run_job.delay(job_id)
