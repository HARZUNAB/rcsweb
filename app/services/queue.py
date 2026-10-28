"""Encolado de trabajos en Celery.

Se aísla en un módulo para poder sustituirlo en los tests sin levantar Redis.
"""

from __future__ import annotations


def encolar_trabajo(job_id: str):
    from tasks.jobs import run_job

    return run_job.delay(job_id)


def encolar_solicitud(request_id: str, password: str):
    from tasks.catalogs import fetch_catalogs

    return fetch_catalogs.delay(request_id, password)
