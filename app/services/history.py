"""Sismicidad histórica para el fondo de los mapas interactivos."""

from __future__ import annotations

import math
import sys
from pathlib import Path

from flask import current_app

MAX_PERFIL = 10000
_CACHE_PERFIL: dict[str, tuple[list[float], list[float]]] = {}


def _plotear():
    core = Path(current_app.config["RCS_CORE_PATH"])
    if str(core) not in sys.path:
        sys.path.insert(0, str(core))
    import plotear  # type: ignore

    return plotear


def _cap(listas: list[list], maximo: int) -> list[list]:
    if not listas:
        return listas
    total = len(listas[0])
    if total <= maximo:
        return listas
    paso = math.ceil(total / maximo)
    return [lista[::paso] for lista in listas]


def perfil(perfil_datos: dict | None, maximo: int = MAX_PERFIL) -> dict:
    if not perfil_datos:
        return {"along": [], "prof": [], "total": 0}
    lon = perfil_datos.get("slab_lon") or []
    lat = perfil_datos.get("slab_lat") or []
    p = perfil_datos.get("slab_p") or []
    if len(lon) < 2 or len(lat) < 2 or len(p) < 2:
        return {"along": [], "prof": [], "total": 0}
    identificador = perfil_datos.get("id", "")
    if identificador and identificador in _CACHE_PERFIL:
        alongs, profs = _CACHE_PERFIL[identificador]
    else:
        try:
            modulo = _plotear()
            datos = modulo._cargar_sismicidad()
        except Exception:
            datos = None
        if datos is None:
            return {"along": [], "prof": [], "total": 0}
        lats, lons, profs = datos

        def _nan(valores):
            return [float(valor) if valor is not None else float("nan") for valor in valores]

        perfil_obj = {
            "id": identificador,
            "slab": {
                "lon": _nan(lon),
                "lat": _nan(lat),
                "p": _nan(p),
            },
        }
        try:
            alongs, profs = modulo._proyectar_hist_perfil(lons, lats, profs, perfil_obj)
        except Exception:
            alongs, profs = [], []
        if identificador:
            _CACHE_PERFIL[identificador] = (alongs, profs)

    total = len(alongs)
    alongs, profs = _cap([alongs, profs], maximo)
    return {"along": alongs, "prof": profs, "total": total}


def datos(perfil_datos: dict | None) -> dict:
    try:
        etiqueta = _plotear().HIST_LABEL
    except Exception:
        etiqueta = "Sismicidad histórica 2020-2026"
    return {
        "perfil": perfil(perfil_datos),
        "label": etiqueta,
    }


__all__ = ["datos", "perfil"]
