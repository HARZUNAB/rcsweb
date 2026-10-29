"""Frontera chilena más cercana, reutilizando ``fronteras.py`` del core."""

from __future__ import annotations

import sys
from pathlib import Path

from flask import current_app


def _modulo():
    core = Path(current_app.config["RCS_CORE_PATH"])
    if str(core) not in sys.path:
        sys.path.insert(0, str(core))
    import fronteras  # type: ignore

    return fronteras


def _mostrar_frontera(lat, lon, modulo, resultado) -> bool:
    """Aplica la regla de mar: solo mostrar en tierra exterior o aguas peruanas."""
    if resultado is None:
        return False
    try:
        datos = modulo._cargar_datos()
    except Exception:
        return True
    if datos is None:
        return True
    try:
        from shapely.geometry import Point

        _fronteras, paises, prep = datos
        punto = Point(float(lon), float(lat))
        if prep["CHL"].contains(punto):
            return False
        for codigo in ("PER", "BOL", "ARG"):
            if prep[codigo].contains(punto):
                return True
        if modulo._es_mar_chileno(float(lon), float(lat), punto, paises, prep):
            return False
        dist_peru = modulo._distancia_tierra_km(float(lon), float(lat), punto, paises["PER"])
        dist_chile = modulo._distancia_tierra_km(float(lon), float(lat), punto, paises["CHL"])
        return dist_peru <= modulo.RADIO_MAR_CHILENO_KM and dist_peru < dist_chile
    except Exception:
        return True


def frontera(lat, lon):
    """(país, km) o None según la regla de la interfaz."""
    try:
        modulo = _modulo()
        resultado = modulo.frontera_mas_cercana(lat, lon)
        if resultado is None:
            return None
        if not _mostrar_frontera(lat, lon, modulo, resultado):
            return None
        return resultado
    except Exception:
        return None


def texto_frontera_coords(lat, lon) -> str:
    """Texto «País — X km» o «—» si no aplica."""
    try:
        modulo = _modulo()
        return modulo.formatear_frontera(frontera(lat, lon))
    except Exception:
        return "—"


def anotar_filas(filas, clave_lat: str, clave_lon: str) -> list[dict]:
    """Agrega Frontera_pais, Frontera_km y Frontera a cada fila."""
    for fila in filas:
        resultado = frontera(fila.get(clave_lat), fila.get(clave_lon))
        if resultado is None:
            fila["Frontera_pais"] = ""
            fila["Frontera_km"] = None
            fila["Frontera"] = "—"
            continue
        pais, km = resultado
        fila["Frontera_pais"] = pais
        fila["Frontera_km"] = km
        try:
            fila["Frontera"] = f"{pais} — {float(km):.1f} km"
        except (TypeError, ValueError):
            fila["Frontera"] = "—"
    return filas


__all__ = ["anotar_filas", "frontera", "texto_frontera_coords"]
