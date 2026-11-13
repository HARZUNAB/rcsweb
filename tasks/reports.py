"""Tareas de informes de revisión."""

from __future__ import annotations

import logging

from .celery_app import celery

log = logging.getLogger(__name__)


@celery.task(name="tasks.generar_informe_revision", bind=True)
def generar_informe_revision(self, report_id: str) -> dict:
    """Genera el informe y crea la solicitud de revisión."""
    from app import create_app
    from app.extensions import db

    aplicacion = create_app()
    with aplicacion.app_context():
        log.info("generar_informe_revision report_id=%s", report_id)
        try:
            from app.services.review_reports import ejecutar

            return ejecutar(report_id)
        except Exception as exc:  # noqa: BLE001 - deja rastro en el estado
            db.session.rollback()
            log.exception("Error en el informe %s", report_id)
            from app.services import review_reports

            review_reports.actualizar_estado(
                report_id,
                estado="error",
                progreso=0,
                paso="Error",
                error=str(exc),
            )
            raise
