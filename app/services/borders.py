"""Frontera chilena más cercana, reutilizando ``fronteras.py`` del core."""

from __future__ import annotations

import sys
from pathlib import Path

from flask import current_app

LON_MIN = -82.0
LON_MAX = -60.0
LAT_MIN = -56.0
LAT_MAX = -14.0
ANCHO_MAPA = 100.0
ALTO_MAPA = 140.0


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


def posicion_mapa(lat, lon) -> dict:
    """Posición del evento en el SVG de planta (viewBox 100x140)."""
    try:
        latitud = float(lat)
        longitud = float(lon)
    except (TypeError, ValueError):
        return {"x": None, "y": None, "visible": False}
    x = (longitud - LON_MIN) / (LON_MAX - LON_MIN) * ANCHO_MAPA
    y = (LAT_MAX - latitud) / (LAT_MAX - LAT_MIN) * ALTO_MAPA
    return {
        "x": round(x, 2),
        "y": round(y, 2),
        "visible": 0 <= x <= ANCHO_MAPA and 0 <= y <= ALTO_MAPA,
    }


def ubicacion(lat, lon) -> str:
    """Chile, Mar o Fuera según los polígonos del core."""
    try:
        latitud = float(lat)
        longitud = float(lon)
        modulo = _modulo()
        datos = modulo._cargar_datos()
    except Exception:
        return ""
    if not (-90 <= latitud <= 90 and -180 <= longitud <= 180):
        return ""
    if datos is None:
        return ""
    try:
        from shapely.geometry import Point

        _fronteras, paises, prep = datos
        punto = Point(longitud, latitud)
        if prep["CHL"].contains(punto):
            return "Chile"
        if modulo._es_mar_chileno(longitud, latitud, punto, paises, prep):
            return "Mar"
        return "Fuera"
    except Exception:
        return ""


def mapa_fila(lat, lon) -> dict:
    """Datos del mini mapa de planta para una fila del listado."""
    datos = posicion_mapa(lat, lon)
    datos["ubicacion"] = ubicacion(lat, lon)
    return datos


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


__all__ = [
    "anotar_filas",
    "frontera",
    "mapa_fila",
    "posicion_mapa",
    "texto_frontera_coords",
    "ubicacion",
]
