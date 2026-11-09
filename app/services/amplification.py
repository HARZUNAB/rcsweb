"""Ampliación de estaciones sin arribos contra la base de SeisComp.

La consulta de inventario y actividad la hace el core incorporado; este módulo
la envuelve para el worker, guarda el resultado en el workspace y coordina el
estado de la tarea en Redis.
"""

from __future__ import annotations

import json
import os
import re
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import redis
from flask import current_app

from ..domain.catalogs import canonical

CLAVE_TAREA = "rcs:ampliacion"
TAREA_TTL = 15 * 60


class AmplificationError(RuntimeError):
    """No se pudo ampliar la lista contra la base."""


def configurada() -> bool:
    """True si hay credenciales de SeisComp configuradas."""
    return all(
        os.environ.get(nombre)
        for nombre in (
            "SEISCOMP_DB_HOST",
            "SEISCOMP_DB_USER",
            "SEISCOMP_DB_PASSWORD",
        )
    )


def clave_radio(radio_km) -> str:
    """Clave estable para el radio: ``sinlimite`` o ``radio500``."""
    if radio_km is None:
        return "sinlimite"
    return f"radio{float(radio_km):g}"


def _id_seguro(event_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(event_id)) or "evento"


def _clave_segura(clave: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(clave)) or "sinlimite"


def ruta_ampliacion(
    workspace: Path, source_id: str, event_id: str, clave: str
) -> Path:
    return (
        workspace
        / "catalogo"
        / source_id
        / "ampliaciones"
        / f"{_id_seguro(event_id)}_{_clave_segura(clave)}.jsonl"
    )


def leer_ampliacion(
    workspace: Path, source_id: str, event_id: str, clave: str
) -> list[dict]:
    ruta = ruta_ampliacion(workspace, source_id, event_id, clave)
    if not ruta.is_file():
        return []
    registros = []
    with ruta.open(encoding="utf-8") as archivo:
        for linea in archivo:
            if linea.strip():
                try:
                    registros.append(json.loads(linea))
                except ValueError:
                    continue
    return registros


def guardar_ampliacion(
    workspace: Path,
    source_id: str,
    event_id: str,
    clave: str,
    filas: list[dict],
) -> Path:
    registros = [
        canonical.estacion_desde_no_picadas_base(fila, source_id, event_id)
        for fila in filas
    ]
    ruta = ruta_ampliacion(workspace, source_id, event_id, clave)
    canonical.escribir_registros(ruta, registros)
    return ruta


@contextmanager
def _entorno_base():
    """Expone las credenciales de SeisComp como RCS_DB_* para el core."""
    if not configurada():
        raise AmplificationError(
            "La base de SeisComp no está configurada en este entorno."
        )
    valores = {
        "RCS_DB_HOST": os.environ.get("SEISCOMP_DB_HOST", ""),
        "RCS_DB_DATABASE": os.environ.get("SEISCOMP_DB_NAME", "seiscomp2"),
        "RCS_DB_USER": os.environ.get("SEISCOMP_DB_USER", ""),
        "RCS_DB_PASSWORD": os.environ.get("SEISCOMP_DB_PASSWORD", ""),
        "PGPORT": os.environ.get("SEISCOMP_DB_PORT", "5432"),
    }
    previos = {clave: os.environ.get(clave) for clave in valores}
    os.environ.update(valores)
    try:
        yield
    finally:
        for clave, valor in previos.items():
            if valor is None:
                os.environ.pop(clave, None)
            else:
                os.environ[clave] = valor


def ampliar_desde_base(
    *,
    base: str,
    instante: datetime,
    id_evento: str,
    id_origen: str,
    latitud: float,
    longitud: float,
    picadas: set[tuple[str, str]],
    radio_km,
) -> tuple[list[dict], int]:
    """Consulta el inventario vigente y devuelve las estaciones sin arribos."""
    # El script del core importa ``disponibilidad`` como módulo hermano.
    core = Path(__file__).resolve().parents[2] / "core"
    if str(core) not in sys.path:
        sys.path.insert(0, str(core))
    from core import exporta_ventana_seiscomp as ex

    from .runner_seiscomp import forzar_solo_lectura

    forzar_solo_lectura()
    with _entorno_base():
        try:
            return ex.no_picadas_de_evento_desde_base(
                base,
                instante,
                id_evento,
                id_origen,
                latitud,
                longitud,
                picadas,
                radio_km=radio_km,
            )
        except Exception as exc:  # noqa: BLE001 - el mensaje va a la interfaz
            raise AmplificationError(
                f"No se pudo consultar la base de SeisComp: {exc}"
            ) from exc


# --- Estado de la tarea en Redis -------------------------------------------


def _redis():
    try:
        url = current_app.config.get(
            "CELERY_RESULT_BACKEND", "redis://redis:6379/1"
        )
    except RuntimeError:
        url = "redis://redis:6379/1"
    return redis.Redis.from_url(
        str(url),
        decode_responses=True,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
    )


def clave_tarea(job_id: str, event_id: str, clave: str) -> str:
    return f"{CLAVE_TAREA}:{job_id}:{event_id}:{clave}"


def tarea_en_curso(job_id: str, event_id: str, clave: str) -> str:
    if not job_id or not event_id or not clave:
        return ""
    try:
        return _redis().get(clave_tarea(job_id, event_id, clave)) or ""
    except redis.RedisError:
        return ""


def registrar_tarea(
    job_id: str, event_id: str, clave: str, task_id: str
) -> tuple[str, bool]:
    if not job_id or not event_id or not clave or not task_id:
        return task_id, True
    try:
        cliente = _redis()
        llave = clave_tarea(job_id, event_id, clave)
        creada = bool(cliente.set(llave, task_id, nx=True, ex=TAREA_TTL))
        if creada:
            return task_id, True
        return cliente.get(llave) or task_id, False
    except redis.RedisError:
        return task_id, True


def limpiar_tarea(job_id: str, event_id: str, clave: str) -> None:
    if not job_id or not event_id or not clave:
        return
    try:
        _redis().delete(clave_tarea(job_id, event_id, clave))
    except redis.RedisError:
        pass
