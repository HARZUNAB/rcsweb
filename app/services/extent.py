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
    aspecto_maximo: float | None = 2.0,
) -> tuple[float, float, float, float]:
    """Amplía ``(lon_min, lon_max, lat_min, lat_max)`` para incluir un punto.

    Se usa en el mapa de Otros para mostrar la costa o islas chilenas más
    cercanas como referencia, sin recortar los eventos del catálogo.

    ``aspecto_maximo`` evita que el mapa quede demasiado ancho y delgado:
    cuando el ancho supera esa proporción respecto del alto, se amplía la
    latitud simétricamente alrededor del centro. Así el mapa de Otros muestra
    más contexto hacia el norte y el sur de Chile.
    """
    lon_min, lon_max, lat_min, lat_max = extent
    lat, lon = punto
    lon_min = min(lon_min, lon - margen_lon)
    lon_max = max(lon_max, lon + margen_lon)
    lat_min = min(lat_min, lat - margen_lat)
    lat_max = max(lat_max, lat + margen_lat)

    if aspecto_maximo and aspecto_maximo > 0:
        ancho = lon_max - lon_min
        alto = lat_max - lat_min
        if ancho / max(alto, 1e-9) > aspecto_maximo:
            alto_objetivo = ancho / aspecto_maximo
            centro = (lat_min + lat_max) / 2
            nuevo_min = centro - alto_objetivo / 2
            nuevo_max = centro + alto_objetivo / 2
            if nuevo_min < -90:
                nuevo_max += -90 - nuevo_min
                nuevo_min = -90.0
            if nuevo_max > 90:
                nuevo_min -= nuevo_max - 90
                nuevo_max = 90.0
            lat_min = max(-90.0, nuevo_min)
            lat_max = min(90.0, nuevo_max)

    return lon_min, lon_max, lat_min, lat_max
