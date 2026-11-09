"""Tarea de ampliación de estaciones sin arribos contra la base de SeisComp."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from .celery_app import celery

log = logging.getLogger(__name__)


def _instante(texto) -> datetime:
    limpio = " ".join(str(texto or "").strip().replace("Z", "+00:00").split())
    instante = datetime.fromisoformat(limpio)
    if instante.tzinfo is not None:
        instante = instante.astimezone(UTC).replace(tzinfo=None)
    return instante


def ejecutar(
    job_id: str,
    source_id: str,
    event_id: str,
    base: str,
    id_origen: str,
    event_time: str,
    latitud: float,
    longitud: float,
    picadas: list,
    radio_km,
) -> dict:
    """Amplía y guarda la lista. Requiere contexto de aplicación."""
    from app.services import amplification
    from app.services.workspace import ruta_workspace

    clave = amplification.clave_radio(radio_km)
    try:
        filas, descartadas = amplification.ampliar_desde_base(
            base=base,
            instante=_instante(event_time),
            id_evento=event_id,
            id_origen=id_origen,
            latitud=float(latitud),
            longitud=float(longitud),
            picadas={tuple(par) for par in picadas},
            radio_km=radio_km,
        )
        amplification.guardar_ampliacion(
            ruta_workspace(job_id),
            source_id,
            event_id,
            clave,
            filas,
        )
        return {
            "estado": "ok",
            "filas": len(filas),
            "descartadas": descartadas,
            "clave": clave,
            "radio": radio_km,
        }
    except amplification.AmplificationError as exc:
        log.warning("No se pudo ampliar: %s", exc)
        return {"estado": "error", "mensaje": str(exc)}
    except Exception as exc:  # noqa: BLE001 - el usuario necesita el motivo
        log.exception("Error al ampliar contra la base")
        return {
            "estado": "error",
            "mensaje": f"No se pudo ampliar contra la base: {exc}",
        }
    finally:
        amplification.limpiar_tarea(job_id, event_id, clave)


@celery.task(name="tasks.ampliar_sin_arribos", bind=True)
def ampliar_sin_arribos(
    self,
    job_id: str,
    source_id: str,
    event_id: str,
    base: str,
    id_origen: str,
    event_time: str,
    latitud: float,
    longitud: float,
    picadas: list,
    radio_km,
) -> dict:
    """Recalcula el inventario de estaciones en un hilo del worker."""
    from app import create_app

    aplicacion = create_app()
    with aplicacion.app_context():
        log.info(
            "ampliar_sin_arribos job=%s source=%s event=%s base=%s radio=%s",
            job_id,
            source_id,
            event_id,
            base,
            radio_km,
        )
        self.update_state(
            state="PROGRESS",
            meta={"fase": "Consultando la base de SeisComp…"},
        )
        return ejecutar(
            job_id,
            source_id,
            event_id,
            base,
            id_origen,
            event_time,
            latitud,
            longitud,
            picadas,
            radio_km,
        )
