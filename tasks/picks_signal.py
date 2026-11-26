"""Tarea de confirmación de señal para estaciones sin aportar."""

from __future__ import annotations

import logging

from .celery_app import celery

log = logging.getLogger(__name__)


@celery.task(name="tasks.analizar_senal_picks", bind=True)
def analizar_senal_picks(
    self,
    job_id: str,
    fuente: str,
    max_eventos: int = 50,
) -> dict:
    """Analiza las formas de onda de las candidatas pendientes.

    Se ejecuta en el worker porque cada evento puede requerir varias
    consultas al servicio de correlación.
    """
    from app import create_app
    from app.services import availability, picks_signal
    from app.services.workspace import ruta_workspace

    aplicacion = create_app()
    with aplicacion.app_context():
        log.info(
            "analizar_senal_picks job=%s fuente=%s max_eventos=%s",
            job_id,
            fuente,
            max_eventos,
        )
        self.update_state(
            state="PROGRESS",
            meta={"fase": "Analizando señal de las candidatas…"},
        )
        try:
            resultado = picks_signal.analizar(
                ruta_workspace(job_id),
                fuente,
                max_eventos=max_eventos,
            )
        except availability.AvailabilityError as exc:
            log.warning("Correlación no disponible: %s", exc)
            return {"estado": "error", "mensaje": str(exc)}
        except Exception as exc:  # noqa: BLE001 - el usuario necesita el motivo
            log.exception("Error al analizar la señal de las candidatas")
            return {
                "estado": "error",
                "mensaje": f"Error al analizar la señal: {exc}",
            }
        if resultado.get("errores") and not resultado.get("eventos"):
            return {
                "estado": "error",
                "mensaje": (
                    "No se pudo consultar el servicio de correlación. "
                    "Los eventos quedaron pendientes."
                ),
            }
        return {"estado": "ok", **resultado}
