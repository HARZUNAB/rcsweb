"""Margen de la planta para los PNG de eventos.

El PNG se genera con el renderizador del core. El margen decide cuánto
contexto rodea a los eventos: más amplio para un evento solo y más ajustado
cuando hay varias soluciones cercanas que deben distinguirse.
"""

from __future__ import annotations

MARGEN_UN_EVENTO = 2.0
MARGEN_MINIMO = 0.01
MARGEN_MAXIMO = 0.6


def margen_planta_eventos(eventos) -> float | None:
    """Margen en grados para la planta, o None si no hay coordenadas.

    - Un punto: vista regional (2.0°).
    - Varios puntos: se ajusta a la separación, entre 0.01° y 0.6°. El piso
      es pequeño a propósito: dos soluciones casi iguales necesitan mucho
      acercamiento para distinguirse.
    """
    puntos = set()
    for evento in eventos or []:
        try:
            puntos.add(
                (round(float(evento["longitud"]), 6), round(float(evento["latitud"]), 6))
            )
        except (TypeError, ValueError, KeyError):
            continue
    if not puntos:
        return None

    lons = [lon for lon, _lat in puntos]
    lats = [lat for _lon, lat in puntos]
    if len(puntos) <= 1:
        return MARGEN_UN_EVENTO

    separacion = max(max(lons) - min(lons), max(lats) - min(lats))
    return min(MARGEN_MAXIMO, max(MARGEN_MINIMO, separacion * 0.5))


def extender_extent(
    extent: tuple[float, float, float, float],
    punto: tuple[float, float],
    margen_lon: float = 2.0,
    margen_lat: float = 1.5,
) -> tuple[float, float, float, float]:
    """Amplía ``(lon_min, lon_max, lat_min, lat_max)`` para incluir un punto.

    Se usa en el mapa de Otros para mostrar la costa o islas chilenas más
    cercanas como referencia, sin recortar los eventos del catálogo.
    """
    lon_min, lon_max, lat_min, lat_max = extent
    lat, lon = punto
    return (
        min(lon_min, lon - margen_lon),
        max(lon_max, lon + margen_lon),
        min(lat_min, lat - margen_lat),
        max(lat_max, lat + margen_lat),
    )
