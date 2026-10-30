"""Enlaces externos de consulta.

El catálogo público de sismologia.cl se publica por día local. El enlace se
arma solo con la fecha del evento (sin hora), que es lo que permite ubicarlo
en la página del día.
"""

from __future__ import annotations

from datetime import datetime

URL_CATALOGO_DIA = (
    "https://www.sismologia.cl/sismicidad/catalogo/{anio}/{mes}/{dia}.html"
)


def url_catalogo_dia(fecha: object) -> str | None:
    """URL del catálogo diario para ``fecha``, o ``None`` si no es válida.

    Acepta ``AAAA-MM-DD HH:MM:SS``, ISO con ``T``/``Z`` o ``AAAA/MM/DD``.
    """
    texto = str(fecha or "").strip()
    if not texto:
        return None
    parte = texto.replace("T", " ").split(" ", 1)[0]
    for formato in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            dia = datetime.strptime(parte, formato)
        except ValueError:
            continue
        return URL_CATALOGO_DIA.format(
            anio=dia.strftime("%Y"),
            mes=dia.strftime("%m"),
            dia=dia.strftime("%Y%m%d"),
        )
    return None
