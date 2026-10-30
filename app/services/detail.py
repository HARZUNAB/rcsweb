"""Detalle de una fila de resultados: deltas y grupos de repetidos."""

from __future__ import annotations

import datetime
import math
from pathlib import Path

from . import colores
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
    ruta = (raiz / archivo).resolve() if "/" in archivo else (
        raiz / "resultados" / archivo
    ).resolve()
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


COLORES_FUENTE = {
    "seiscomp": "#0d6efd",
    "seisan": "#fd7e14",
    "eventquery": "#198754",
    "publicado": "#6c757d",
}
ETIQUETAS_FUENTE = {
    "seiscomp": "SeisComp",
    "seisan": "Seisan",
    "eventquery": "Eventquery",
    "publicado": "Publicado",
}


def _texto(valor) -> str:
    return "" if valor is None else str(valor).strip()


def _punto(
    fuente: str,
    fecha,
    lat,
    lon,
    prof,
    mag,
    tipo,
    analista="",
    estado="",
    fila=None,
    rol=None,
    percibido="",
) -> dict | None:
    latitud = _a_numero(lat)
    longitud = _a_numero(lon)
    if latitud is None or longitud is None:
        return None
    # El color ya no identifica a la fuente: sigue la paleta del proyecto base.
    # ``rol`` distingue local/publicado y ``percibido`` el rojo de Eventquery.
    codigo = fuente if fuente in COLORES_FUENTE else "publicado"
    estilo = colores.estilo_punto(
        codigo, {"rol": rol, "percibido": percibido, "sospechoso": False}
    )
    return {
        "fuente": codigo,
        "etiqueta": ETIQUETAS_FUENTE[codigo],
        "color": estilo["color"],
        "borde": estilo["borde"],
        "borde_ancho": estilo["borde_ancho"],
        "rol": rol,
        "percibido": _texto(percibido),
        "fecha": _texto(fecha),
        "lat": latitud,
        "lon": longitud,
        "prof": _a_numero(prof),
        "mag": _texto(mag),
        "tipo": _texto(tipo),
        "analista": _texto(analista),
        "estado": _texto(estado),
        "fila": fila,
    }


def puntos_mapa(
    tabla: str, fila: dict, opcion: str, grupo=None, indice: int | None = None
) -> list[dict]:
    """Puntos del detalle para el mapa interactivo."""
    puntos = []
    if tabla == "no_actualizados":
        local = _punto(
            opcion,
            fila.get("fecha_local"),
            fila.get("lat_local"),
            fila.get("lon_local"),
            fila.get("prof_local"),
            fila.get("mag_local"),
            fila.get("tipo_mag_local"),
            fila.get("analista", ""),
            rol="local",
        )
        publicado = _punto(
            "eventquery",
            fila.get("fecha_eventquery"),
            fila.get("lat_eventquery"),
            fila.get("lon_eventquery"),
            fila.get("prof_eventquery"),
            fila.get("mag_eventquery"),
            fila.get("tipo_mag_eventquery"),
            rol="publicado",
        )
        puntos.extend(p for p in (local, publicado) if p is not None)
        referencia = local or (puntos[0] if puntos else None)
    elif tabla == "repetidos":
        fuente = opcion.split("_", 1)[0]
        if fuente == "publica":
            fuente = "eventquery"
        for item in grupo or []:
            datos = item.get("fila", {})
            punto = _punto(
                fuente,
                datos.get("fecha_hora"),
                datos.get("latitud"),
                datos.get("longitud"),
                datos.get("prof"),
                datos.get("mag"),
                datos.get("tipomag"),
                datos.get("analista", ""),
                fila=item.get("_fila"),
                percibido=datos.get("percibido", ""),
            )
            if punto is not None:
                puntos.append(punto)
        referencia = next((p for p in puntos if p.get("fila") == indice), None)
        if referencia is None and puntos:
            referencia = puntos[0]
    else:
        punto = _punto(
            opcion,
            fila.get("Fecha_Hora"),
            fila.get("Latitud"),
            fila.get("Longitud"),
            fila.get("Prof."),
            fila.get("Mag."),
            fila.get("Tipo_mag."),
            fila.get("Analista", ""),
            fila.get("Estado", ""),
            percibido=fila.get("Percep.", ""),
        )
        if punto is not None:
            puntos.append(punto)
        referencia = punto

    if referencia is not None:
        for punto in puntos:
            punto["dist_km"] = distancia_km(
                referencia.get("lat"),
                referencia.get("lon"),
                punto.get("lat"),
                punto.get("lon"),
            )
            if punto["dist_km"] is not None:
                punto["dist_km"] = round(punto["dist_km"], 1)
    return puntos


def superpuestos(puntos: list[dict], perfil: bool = False) -> bool:
    """True si hay soluciones de fuentes distintas en la misma ubicación.

    En planta se redondea a 3 decimales y en perfil a 1 decimal en ``along`` y
    ``prof``, igual que ``plotear.py``. Se usa para el aro magenta y la leyenda.
    """
    vistos: dict[tuple, set] = {}
    for punto in puntos:
        if perfil:
            along = punto.get("along_km")
            prof = punto.get("prof")
            if along is None or prof is None:
                continue
            clave = (round(float(along), 1), round(float(prof), 1))
        else:
            lat = punto.get("lat")
            lon = punto.get("lon")
            if lat is None or lon is None:
                continue
            clave = (round(float(lat), 3), round(float(lon), 3))
        vistos.setdefault(clave, set()).add(punto.get("fuente"))
    return any(len(fuentes) > 1 for fuentes in vistos.values())


def leyenda_detalle(
    tabla: str,
    opcion: str,
    puntos: list[dict],
    hay_sospechosos: bool,
    hay_superpuestos: bool,
) -> list[dict]:
    """Ítems de leyenda con los colores del proyecto base.

    Se arma con los roles presentes: local, publicado, Eventquery percibido o
    no percibido. El aro de selección y el de superposición se agregan aparte.
    """
    items: list[dict] = []
    roles = {punto.get("rol") for punto in puntos if punto.get("rol")}
    if "publicado" in roles or "local" in roles:
        etiqueta = ETIQUETAS_FUENTE.get(opcion, opcion)
        items.append(
            {
                "etiqueta": f"Evento {etiqueta}",
                "relleno": colores.COLOR_NO_PERCIBIDO,
                "borde": "#000000",
                "borde_ancho": 1.2,
            }
        )
        if "publicado" in roles:
            items.append(
                {
                    "etiqueta": "Publicado",
                    "relleno": "#ffffff",
                    "borde": colores.COLOR_PUBLICADO,
                    "borde_ancho": 2.0,
                }
            )
    else:
        fuente = next(
            (punto.get("fuente") for punto in puntos if punto.get("fuente")),
            opcion,
        )
        if fuente == "eventquery" or opcion == "eventquery":
            items.extend(
                [
                    {
                        "etiqueta": "Sismo no percibido",
                        "relleno": colores.COLOR_NO_PERCIBIDO,
                        "borde": "#000000",
                        "borde_ancho": 1.2,
                    },
                    {
                        "etiqueta": "Sismo percibido",
                        "relleno": colores.COLOR_PERCIBIDO,
                        "borde": "#000000",
                        "borde_ancho": 1.2,
                    },
                ]
            )
        else:
            items.append(
                {
                    "etiqueta": "Sismo registrado",
                    "relleno": colores.COLOR_NO_PERCIBIDO,
                    "borde": "#000000",
                    "borde_ancho": 1.2,
                }
            )
    if hay_sospechosos:
        items.append(
            {
                "etiqueta": "Sospechoso (borde violeta)",
                "relleno": colores.COLOR_NEUTRO,
                "borde": colores.COLOR_BORDE_SOSPECHOSO,
                "borde_ancho": colores.GROSOR_BORDE_SOSPECHOSO,
            }
        )
    items.append(
        {
            "etiqueta": "Evento seleccionado",
            "relleno": "transparent",
            "borde": colores.COLOR_RESALTADO,
            "borde_ancho": 2.0,
        }
    )
    if hay_superpuestos:
        items.append(
            {
                "etiqueta": "Soluciones superpuestas",
                "relleno": "transparent",
                "borde": colores.COLOR_SUPERPUESTO,
                "borde_ancho": 2.0,
            }
        )
    return items


def clave_evento(punto: dict) -> str:
    """Clave estable para emparejar un punto del mapa con uno del perfil.

    Usa fuente + coordenadas redondeadas + profundidad. El mapa de planta y el
    perfil arman sus puntos por separado, así que necesitan una clave común
    para resaltar el mismo evento en las dos vistas.
    """

    def numero(valor, decimales):
        try:
            return f"{float(valor):.{decimales}f}"
        except (TypeError, ValueError):
            return ""

    return "|".join(
        (
            str(punto.get("fuente") or ""),
            numero(punto.get("lat"), 5),
            numero(punto.get("lon"), 5),
            numero(punto.get("prof"), 1),
        )
    )


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
    elif tabla == "catalogos":
        campos = [
            ("Fecha_Hora", "Fecha y hora"),
            ("Latitud", "Latitud"),
            ("Longitud", "Longitud"),
            ("Prof.", "Profundidad (km)"),
            ("Mag.", "Magnitud"),
            ("Tipo_mag.", "Tipo de magnitud"),
        ]
        if "Analista probable" in fila:
            campos.append(("Analista probable", "Analista probable"))
        elif "Analista" in fila:
            campos.append(("Analista", "Analista"))
        campos.extend(
            [
                ("Referencia", "Referencia"),
                ("Percep.", "Percibido"),
            ]
        )
        contexto["campos_local"] = campos
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
    "clave_evento",
    "construir_detalle",
    "distancia_km",
    "grupo_repetidos",
    "leer_fila",
    "puntos_mapa",
    "leer_filas",
]
