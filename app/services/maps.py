"""Detección de conectividad para elegir el mapa online u offline."""

from __future__ import annotations

import os
import time

import requests

_TILE_URL = "https://tile.openstreetmap.org/0/0/0.png"
_CACHE = {"ts": 0.0, "online": None}
_TTL = 300.0


def internet_disponible(timeout: float = 2.0) -> bool:
    ahora = time.monotonic()
    if _CACHE["online"] is not None and ahora - _CACHE["ts"] < _TTL:
        return bool(_CACHE["online"])
    try:
        respuesta = requests.head(_TILE_URL, timeout=timeout, allow_redirects=True)
        online = respuesta.ok
    except requests.RequestException:
        online = False
    _CACHE["ts"] = ahora
    _CACHE["online"] = online
    return online


def modo_mapa(forzado: str | None = None) -> str:
    """online | offline, con override por query o MAPS_MODE."""
    if forzado in ("online", "offline"):
        return forzado
    configurado = os.environ.get("MAPS_MODE", "auto").strip().lower()
    if configurado in ("online", "offline"):
        return configurado
    return "online" if internet_disponible() else "offline"


__all__ = ["internet_disponible", "modo_mapa"]
