"""Tareas de adquisición de catálogos."""

from __future__ import annotations

import logging

from .celery_app import celery

log = logging.getLogger(__name__)


@celery.task(name="tasks.fetch_catalogs", bind=True)
def fetch_catalogs(self, request_id: str, password: str) -> dict:
    """Descarga los catálogos de una solicitud y crea el trabajo."""
    from app import create_app
    from app.services.acquisition import ejecutar_solicitud

    aplicacion = create_app()
    with aplicacion.app_context():
        log.info("fetch_catalogs request_id=%s", request_id)
        try:
            return ejecutar_solicitud(request_id, password)
        except Exception as exc:  # noqa: BLE001 - deja rastro en la solicitud
            from datetime import UTC, datetime

            from app.extensions import db
            from app.models import CatalogRequest

            solicitud = db.session.get(CatalogRequest, request_id)
            if solicitud is not None:
                solicitud.status = "failed"
                solicitud.error = f"Error interno del worker: {exc}"
                solicitud.current_step = "Error"
                solicitud.finished_at = datetime.now(UTC)
                db.session.commit()
            raise
