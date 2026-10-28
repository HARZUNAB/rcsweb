"""Detalle de una fila de resultados: deltas y grupos de repetidos."""

from __future__ import annotations

import datetime
import math
from pathlib import Path

from .results import _a_numero, leer_csv

CAMPOS_NO_PUBLICADO_LOCAL = (
    ("Fecha_Hora", "Fecha y hora"),
    ("Latitud", "Latitud"),
    ("Longitud", "Longitud"),
    ("Prof.", "Prof. (km)"),
    ("Mag.", "Magnitud"),
    ("Tipo_mag.", "Tipo de magnitud"),
    ("Analista", "Analista"),
)

CAMPOS_NO_PUBLICADO_OTRA = (
    ("Publicado_en", "Publicado en"),
    ("Estado", "Estado"),
    ("Dt_otra_seg", "Δt otra fuente (s)"),
    ("Dist_otra_km", "Distancia otra fuente (km)"),
    ("Analista_otra", "Analista otra fuente"),
)

CAMPOS_REPETIDO = (
    ("fecha_hora", "Fecha y hora"),
    ("latitud", "Latitud"),
    ("longitud", "Longitud"),
    ("prof", "Prof. (km)"),
    ("mag", "Magnitud"),
    ("tipomag", "Tipo de magnitud"),
    ("referencia", "Referencia"),
    ("percibido", "Percibido"),
    ("analista", "Analista"),
    ("analista_seisan", "Analista probable (Seisan)"),
    ("analista_seiscomp", "Analista probable (SeisComp)"),
)


def leer_filas(workspace: Path, archivo: str):
    """(columnas, filas) del CSV de resultados, o None si no es accesible."""
    raiz = workspace.resolve()
    ruta = (raiz / "resultados" / archivo).resolve()
    if not ruta.is_file() or not ruta.is_relative_to(raiz):
        return None
    return leer_csv(ruta)


def leer_fila(workspace: Path, archivo: str, indice: int):
    """(columnas, fila) en la posición indicada del CSV de resultados."""
    leido = leer_filas(workspace, archivo)
    if leido is None:
        return None
    columnas, filas = leido
    if indice < 0 or indice >= len(filas):
        return None
    return columnas, filas[indice]


def _instante(texto):
    if texto is None:
        return None
    limpio = " ".join(str(texto).strip().split())
    if limpio.endswith("Z"):
        limpio = limpio[:-1]
    limpio = limpio.replace("T", " ")
    if len(limpio) >= 2 and limpio[-2:] == "60":
        limpio = limpio[:-2] + "59"
    for formato in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(limpio, formato)
        except ValueError:
            continue
    return None


def _delta_numerico(fuente, publicado, decimales: int):
    a = _a_numero(fuente)
    b = _a_numero(publicado)
    if a is None or b is None:
        return ""
    return round(b - a, decimales)


def _formatear_delta(valor, decimales: int, sufijo: str = "") -> str:
    if valor == "" or valor is None:
        return "—"
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return str(valor)
    signo = "+" if numero > 0 else ""
    return f"{signo}{numero:.{decimales}f}{sufijo}"


def _comparaciones(fila: dict) -> list[dict]:
    """Filas de la tabla comparativa fuente vs publicado."""
    discrepancias = {
        parte.strip() for parte in str(fila.get("discrepancias", "")).split(",") if parte.strip()
    }

    def _coincide(clave: str) -> bool:
        return clave not in discrepancias

    dlat = _delta_numerico(fila.get("lat_local"), fila.get("lat_eventquery"), 3)
    dlon = _delta_numerico(fila.get("lon_local"), fila.get("lon_eventquery"), 3)
    dprof = _delta_numerico(fila.get("prof_local"), fila.get("prof_eventquery"), 1)
    dmag = _delta_numerico(fila.get("mag_local"), fila.get("mag_eventquery"), 1)

    return [
        {
            "parametro": "Fecha y hora",
            "fuente": fila.get("fecha_local", ""),
            "publicado": fila.get("fecha_eventquery", ""),
            "delta": _formatear_delta(fila.get("dt_seg"), 1, " s"),
            "coincide": True,
        },
        {
            "parametro": "Latitud",
            "fuente": fila.get("lat_local", ""),
            "publicado": fila.get("lat_eventquery", ""),
            "delta": _formatear_delta(dlat, 3, "°"),
            "coincide": _coincide("lat"),
        },
        {
            "parametro": "Longitud",
            "fuente": fila.get("lon_local", ""),
            "publicado": fila.get("lon_eventquery", ""),
            "delta": _formatear_delta(dlon, 3, "°"),
            "coincide": _coincide("lon"),
        },
        {
            "parametro": "Profundidad",
            "fuente": fila.get("prof_local", ""),
            "publicado": fila.get("prof_eventquery", ""),
            "delta": _formatear_delta(dprof, 1, " km"),
            "coincide": _coincide("prof"),
        },
        {
            "parametro": "Magnitud",
            "fuente": fila.get("mag_local", ""),
            "publicado": fila.get("mag_eventquery", ""),
            "delta": _formatear_delta(dmag, 1),
            "coincide": _coincide("mag"),
        },
    ]


def _grupo_repetidos(filas: list[dict], indice: int, archivo: str) -> list[dict]:
    if indice < 0 or indice >= len(filas):
        return []
    seleccionada = filas[indice]
    ventana_seg, tolerancia = (6.0, 2.0) if "amplio" in archivo else (3.0, 1.0)
    instante = _instante(seleccionada.get("fecha_hora"))
    lat = _a_numero(seleccionada.get("latitud"))
    lon = _a_numero(seleccionada.get("longitud"))

    grupo = []
    for posicion, fila in enumerate(filas):
        if instante is not None:
            otro = _instante(fila.get("fecha_hora"))
            if otro is None:
                continue
            dt = abs((otro - instante).total_seconds())
            if dt > ventana_seg:
                continue
        else:
            dt = None

        dlat = dlon = None
        if lat is not None and lon is not None:
            otra_lat = _a_numero(fila.get("latitud"))
            otra_lon = _a_numero(fila.get("longitud"))
            if otra_lat is not None and otra_lon is not None:
                dlat = abs(otra_lat - lat)
                dlon = abs(otra_lon - lon)
                if dlat > tolerancia or dlon > tolerancia:
                    continue

        grupo.append(
            {
                "_fila": posicion,
                "fila": fila,
                "dt_seg": None if dt is None else round(dt, 1),
                "dlat": None if dlat is None else round(dlat, 3),
                "dlon": None if dlon is None else round(dlon, 3),
            }
        )
    return grupo


def grupo_repetidos(filas: list[dict], indice: int, archivo: str) -> list[dict]:
    """Grupo de duplicados alrededor de una fila (ventana según el informe)."""
    return _grupo_repetidos(filas, indice, archivo)


def construir_detalle(tabla: str, archivo: str, filas: list[dict], indice: int) -> dict:
    fila = filas[indice]
    contexto = {
        "fila": fila,
        "distancia": fila.get("dist_km", ""),
        "discrepancias": fila.get("discrepancias", ""),
        "revision": fila.get("revision", ""),
        "publicacion": fila.get("publicacion_probable", ""),
    }

    if tabla == "no_actualizados":
        contexto["comparaciones"] = _comparaciones(fila)
    elif tabla == "repetidos":
        contexto["grupo"] = grupo_repetidos(filas, indice, archivo)
        contexto["campos_repetido"] = [
            (clave, titulo) for clave, titulo in CAMPOS_REPETIDO if clave in fila
        ]
    else:
        contexto["campos_local"] = CAMPOS_NO_PUBLICADO_LOCAL
        contexto["campos_otra"] = CAMPOS_NO_PUBLICADO_OTRA

    return contexto


def distancia_km(lat1, lon1, lat2, lon2):
    valores = [_a_numero(lat1), _a_numero(lon1), _a_numero(lat2), _a_numero(lon2)]
    if any(valor is None for valor in valores):
        return None
    la1, lo1, la2, lo2 = valores
    phi1, phi2 = math.radians(la1), math.radians(la2)
    dphi = math.radians(la2 - la1)
    dlambda = math.radians(lo2 - lo1)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(h)))


# `_parametros_discrepantes` se importa para que el detalle pueda recalcular
# discrepancias si el CSV viene de una corrida anterior sin la columna.
__all__ = [
    "CAMPOS_NO_PUBLICADO_LOCAL",
    "CAMPOS_NO_PUBLICADO_OTRA",
    "CAMPOS_REPETIDO",
    "construir_detalle",
    "distancia_km",
    "grupo_repetidos",
    "leer_fila",
    "leer_filas",
]
