"""Colores y estilos de eventos alineados con ``plotear.py`` del core.

La clasificación es la del proyecto base: amarillo para sismos registrados o
no percibidos, rojo para Eventquery percibido, aro blanco/negro para la
solución publicada, borde violeta para sospechosos, aro azul marino para el
evento seleccionado y aro magenta para soluciones superpuestas.
"""

from __future__ import annotations

# Paleta del proyecto base (plotear.py). No se usan colores por fuente para
# evitar que dos catálogos distintos se confundan: manda el rol y la percepción.
COLOR_PERCIBIDO = "#c00000"
COLOR_NO_PERCIBIDO = "#ffff00"
COLOR_PUBLICADO = "#000000"
COLOR_BORDE_SOSPECHOSO = "#7b1196"
GROSOR_BORDE_SOSPECHOSO = 3.0
COLOR_NEUTRO = "#bfbfbf"
COLOR_RESALTADO = "#000080"
COLOR_SUPERPUESTO = "#ff00ff"


def _percibido(valor) -> bool:
    return str(valor or "").strip().upper() == "S"


def color_relleno(fuente: str, evento: dict) -> str:
    """Relleno del marcador según rol, fuente y percepción.

    La solución publicada se dibuja como anillo blanco con borde negro; el
    resto usa amarillo, salvo Eventquery percibido, que va en rojo.
    """
    if evento.get("rol") == "publicado":
        return "#ffffff"
    if fuente == "eventquery" and _percibido(evento.get("percibido")):
        return COLOR_PERCIBIDO
    return COLOR_NO_PERCIBIDO


def estilo_punto(fuente: str, evento: dict) -> dict:
    """Relleno, color de borde y grosor del borde para un evento.

    El borde violeta del sospechoso tiene prioridad sobre el borde normal. El
    aro de selección y el de superposición se agregan en el cliente porque
    dependen de la interacción, no del evento.
    """
    if evento.get("rol") == "publicado":
        borde, ancho = COLOR_PUBLICADO, 2.0
    elif evento.get("sospechoso"):
        borde, ancho = COLOR_BORDE_SOSPECHOSO, GROSOR_BORDE_SOSPECHOSO
    else:
        borde, ancho = "#000000", 1.2
    return {
        "color": color_relleno(fuente, evento),
        "borde": borde,
        "borde_ancho": ancho,
    }


__all__ = [
    "COLOR_BORDE_SOSPECHOSO",
    "COLOR_NEUTRO",
    "COLOR_NO_PERCIBIDO",
    "COLOR_PERCIBIDO",
    "COLOR_PUBLICADO",
    "COLOR_RESALTADO",
    "COLOR_SUPERPUESTO",
    "GROSOR_BORDE_SOSPECHOSO",
    "color_relleno",
    "estilo_punto",
]
