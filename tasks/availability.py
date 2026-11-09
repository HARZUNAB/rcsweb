"""Tarea de consulta de disponibilidad de formas de onda."""

from __future__ import annotations

import logging

from .celery_app import celery

log = logging.getLogger(__name__)


def ejecutar(
    job_id: str,
    source_id: str,
    event_id: str,
    event_time: str,
    filas: list[dict],
    vista: str = "",
) -> dict:
    """Consulta y guarda la disponibilidad. Requiere contexto de aplicación."""
    from app.services import availability
    from app.services.workspace import ruta_workspace

    try:
        streams = availability.streams_de_filas(filas)
        resultados = availability.consultar(event_time, streams)
        resumen = availability.aplicar_a_filas(filas, resultados)
        if resumen["con_datos"] == 0 and resumen["sin_datos"] == 0:
            return {
                "estado": "error",
                "mensaje": (
                    "No se pudo consultar ninguna fuente de formas de onda. "
                    "Revise el SDS y el tiempo real."
                ),
            }
        availability.guardar_cache(
            ruta_workspace(job_id),
            source_id,
            event_id,
            filas,
        )
        return {"estado": "ok", **resumen}
    except availability.AvailabilityError as exc:
        log.warning("Disponibilidad no disponible: %s", exc)
        return {"estado": "error", "mensaje": str(exc)}
    except Exception as exc:  # noqa: BLE001 - el usuario necesita el motivo
        log.exception("Error al consultar disponibilidad")
        return {
            "estado": "error",
            "mensaje": f"Error al consultar formas de onda: {exc}",
        }
    finally:
        availability.limpiar_tarea(job_id, event_id, vista)


@celery.task(name="tasks.consultar_disponibilidad", bind=True)
def consultar_disponibilidad(
    self,
    job_id: str,
    source_id: str,
    event_id: str,
    event_time: str,
    filas: list[dict],
    vista: str = "",
) -> dict:
    """Consulta el sidecar y guarda la disponibilidad del evento.

    Se ejecuta en el worker para no bloquear una petición web: la consulta a
    ``scart`` puede tardar decenas de segundos.
    """
    from app import create_app

    aplicacion = create_app()
    with aplicacion.app_context():
        log.info(
            "consultar_disponibilidad job=%s source=%s event=%s filas=%s",
            job_id,
            source_id,
            event_id,
            len(filas),
        )
        self.update_state(
            state="PROGRESS",
            meta={"fase": "Consultando formas de onda…"},
        )
        return ejecutar(
            job_id, source_id, event_id, event_time, filas, vista
        )
