"""Bandeja temporal de eventos para solicitudes de revisión.

Los eventos se acumulan por usuario y trabajo en Redis, con TTL. Al enviar
se agrupan por responsable para generar una sola solicitud y un solo PDF por
analista.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import redis
from flask import current_app

CLAVE_BANDEJA = "rcs:revision:bandeja"
TTL_BANDEJA = 12 * 3600
MAX_ENVIO_SEG = 2 * 3600


class BandejaError(RuntimeError):
    """No se pudo guardar o leer la bandeja temporal."""


def _redis():
    url = current_app.config.get(
        "CELERY_RESULT_BACKEND", "redis://redis:6379/1"
    )
    return redis.Redis.from_url(
        str(url),
        decode_responses=True,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
    )


def clave(job_id: str, user_id: int) -> str:
    return f"{CLAVE_BANDEJA}:{job_id}:{user_id}"


def listar(job_id: str, user_id: int) -> list[dict]:
    clave_actual = clave(job_id, user_id)
    try:
        conexion = _redis()
        texto = conexion.get(clave_actual)
        if texto:
            conexion.expire(clave_actual, TTL_BANDEJA)
    except redis.RedisError as exc:
        raise BandejaError(f"No se pudo leer la bandeja: {exc}") from exc
    if not texto:
        return []
    try:
        datos = json.loads(texto)
    except ValueError:
        return []
    if not isinstance(datos, list):
        return []
    items = [item for item in datos if isinstance(item, dict)]
    restaurados = _restaurar_vencidos(items)
    if restaurados:
        _guardar(job_id, user_id, items)
    return items


def _restaurar_vencidos(items: list[dict]) -> bool:
    """Devuelve a pendiente los envíos que quedaron colgados."""
    ahora = datetime.now(UTC)
    cambiado = False
    for item in items:
        if item.get("estado") != "enviando":
            continue
        enviado = str(item.get("enviado_en") or "")
        try:
            instante = datetime.fromisoformat(enviado)
        except ValueError:
            instante = ahora
        if (ahora - instante).total_seconds() > MAX_ENVIO_SEG:
            item["estado"] = "pendiente"
            item.pop("report_id", None)
            item.pop("enviado_en", None)
            cambiado = True
    return cambiado


def ttl_restante(job_id: str, user_id: int) -> int:
    try:
        valor = _redis().ttl(clave(job_id, user_id))
    except redis.RedisError:
        return 0
    try:
        return max(0, int(valor))
    except (TypeError, ValueError):
        return 0


def claves(item: dict) -> tuple[str, str]:
    fila = item.get("fila") or {}
    return (
        str(fila.get("fuente") or ""),
        str(fila.get("evento") or ""),
    )


def marcar_enviando(
    job_id: str,
    user_id: int,
    claves_enviadas: set[tuple[str, str]],
    report_id: str,
) -> None:
    items = listar(job_id, user_id)
    for item in items:
        if claves(item) in claves_enviadas:
            item["estado"] = "enviando"
            item["report_id"] = report_id
            item["enviado_en"] = datetime.now(UTC).isoformat()
    _guardar(job_id, user_id, items)


def quitar_enviados(job_id: str, user_id: int, report_id: str) -> None:
    items = [
        item
        for item in listar(job_id, user_id)
        if str(item.get("report_id") or "") != str(report_id)
    ]
    _guardar(job_id, user_id, items)


def restaurar(job_id: str, user_id: int, report_id: str) -> None:
    items = listar(job_id, user_id)
    for item in items:
        if str(item.get("report_id") or "") == str(report_id):
            item["estado"] = "pendiente"
            item.pop("report_id", None)
            item.pop("enviado_en", None)
    _guardar(job_id, user_id, items)


def _guardar(job_id: str, user_id: int, items: list[dict]) -> None:
    try:
        if items:
            _redis().set(
                clave(job_id, user_id),
                json.dumps(items, ensure_ascii=False),
                ex=TTL_BANDEJA,
            )
        else:
            _redis().delete(clave(job_id, user_id))
    except redis.RedisError as exc:
        raise BandejaError(f"No se pudo guardar la bandeja: {exc}") from exc


def agregar(job_id: str, user_id: int, item: dict) -> list[dict]:
    """Agrega o reemplaza un evento, identificado por fuente y evento."""
    fila = item.get("fila") or {}
    fuente = str(fila.get("fuente") or "")
    evento = str(fila.get("evento") or "")
    if not fuente or not evento:
        raise BandejaError("El evento no tiene fuente o identificador.")
    items = listar(job_id, user_id)
    nuevos = [
        actual
        for actual in items
        if (
            str((actual.get("fila") or {}).get("fuente") or ""),
            str((actual.get("fila") or {}).get("evento") or ""),
        )
        != (fuente, evento)
    ]
    nuevos.append(
        {
            **item,
            "agregado_en": datetime.now(UTC).isoformat(),
        }
    )
    _guardar(job_id, user_id, nuevos)
    return nuevos


def quitar(job_id: str, user_id: int, fuente: str, evento: str) -> list[dict]:
    items = [
        actual
        for actual in listar(job_id, user_id)
        if (
            str((actual.get("fila") or {}).get("fuente") or ""),
            str((actual.get("fila") or {}).get("evento") or ""),
        )
        != (str(fuente), str(evento))
    ]
    _guardar(job_id, user_id, items)
    return items


def reemplazar(job_id: str, user_id: int, items: list[dict]) -> None:
    _guardar(job_id, user_id, items)


def vaciar(job_id: str, user_id: int) -> None:
    _guardar(job_id, user_id, [])
