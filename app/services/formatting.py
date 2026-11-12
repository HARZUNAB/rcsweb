"""Formato numérico común para tablas, detalles y reportes.

El catálogo canónico conserva la precisión completa. Estas funciones se usan
solo en la presentación y en los CSV derivados, para que todas las vistas
muestren la misma cantidad de decimales.
"""

from __future__ import annotations


def numero(
    valor,
    decimales: int = 2,
    *,
    signo: bool = False,
    cero_cercano: bool = True,
) -> str:
    """Formatea un número con un máximo de decimales.

    Si el valor no es cero pero redondea a cero, devuelve ``<0.01`` (o el
    límite que corresponda) para no mostrar un cero engañoso.
    """
    try:
        numero_valor = float(str(valor).strip())
    except (TypeError, ValueError):
        return "" if valor is None else str(valor).strip()
    if cero_cercano and numero_valor != 0:
        limite = 10 ** (-decimales)
        if abs(numero_valor) < limite:
            return f"<{limite:.{decimales}f}"
    formato = f"{{:+.{decimales}f}}" if signo else f"{{:.{decimales}f}}"
    return formato.format(numero_valor)


def entero(valor) -> str:
    return numero(valor, 0, cero_cercano=False)


def peso_04(valor) -> float | None:
    """Convierte el peso canónico 0–1 a la escala 0–4 que usan los analistas.

    0 es mayor influencia y 4 equivale a sin influencia.
    """
    try:
        canonico = float(str(valor).strip())
    except (TypeError, ValueError):
        return None
    return max(0.0, min(4.0, 4.0 * (1.0 - canonico)))


ETIQUETAS_PATRON = {
    "puntual": "Puntual",
    "sistemático": "Sistemático",
    "mixto": "Mixto",
    "fuera_de_orden": "Fase inconsistente con la distancia",
    "fuera_de_orden_debil": (
        "Fase inconsistente con la distancia (baja influencia)"
    ),
    "pick_antes_origen": "Pick antes del origen",
    "sin_patron": "Sin patrón",
    "sin_datos": "Sin datos",
    "sin_fase": "Sin inconsistencia de fases",
}

ETIQUETAS_TIPO_INDICIO = {
    "residual_alto": "Residual alto",
    "fuera_de_orden": "Fase inconsistente con la distancia",
    "fuera_de_orden_debil": (
        "Fase inconsistente con la distancia (baja influencia)"
    ),
    "pick_antes_origen": "Pick antes del origen",
    "patron_sistematico": "Patrón sistemático",
    "solución_sospechosa": "Solución sospechosa",
}


def patron_texto(valor) -> str:
    texto = "" if valor is None else str(valor).strip()
    return ETIQUETAS_PATRON.get(texto, texto)


def patron_corto(valor) -> str:
    texto = "" if valor is None else str(valor).strip()
    if texto in ("fuera_de_orden", "fuera_de_orden_debil"):
        corto = patron_texto(texto).replace("Fase ", "", 1)
        return corto[:1].upper() + corto[1:]
    return patron_texto(texto)


def tipo_indicio_texto(valor) -> str:
    texto = "" if valor is None else str(valor).strip()
    return ETIQUETAS_TIPO_INDICIO.get(texto, texto)


def tipos_indicio_texto(valor) -> str:
    texto = "" if valor is None else str(valor).strip()
    if not texto:
        return ""
    return ", ".join(
        tipo_indicio_texto(parte) for parte in texto.split(",") if parte.strip()
    )


def peso_04_texto(valor) -> str:
    convertido = peso_04(valor)
    return "" if convertido is None else f"{convertido:.0f}"


def peso_original(raw: dict | None) -> str:
    """Valor original del peso, para la línea secundaria del detalle.

    Seisan conserva ``peso_w`` (0–4). Central y SeisComp dejan su valor en
    ``peso``; si es muy pequeño se muestra en notación científica.
    """
    raw = raw or {}
    if raw.get("peso_w") is not None:
        return f"W={numero(raw.get('peso_w'), 0, cero_cercano=False)}"
    valor = raw.get("peso")
    try:
        original = float(str(valor).strip())
    except (TypeError, ValueError):
        return ""
    if original != 0 and abs(original) < 0.001:
        return f"{original:.1e}"
    return f"{original:g}"


__all__ = [
    "entero",
    "numero",
    "patron_corto",
    "patron_texto",
    "peso_04",
    "peso_04_texto",
    "peso_original",
    "tipo_indicio_texto",
    "tipos_indicio_texto",
]
