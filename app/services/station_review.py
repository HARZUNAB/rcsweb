"""Revisión de estaciones por evento.

El servicio lee solo archivos canónicos: eventos, arribos y estaciones sin
arribos. No conoce formatos de fuente ni compara nombres de catálogo. Cuando una
fuente declara la capacidad de arribos pero el trabajo no trae los archivos,
devuelve un estado «no evaluable» con un motivo genérico.
"""

from __future__ import annotations

import datetime
import math
from pathlib import Path

from ..domain.catalogs import canonical
from ..domain.catalogs import manifest as fuentes_manifest
from . import amplification, availability

MOTIVO_SIN_REVISION = "Este trabajo no incluye la revisión de estaciones."
MOTIVO_EVENTO = "El evento no está en la revisión de estaciones de este trabajo."
MOTIVO_SIN_ARCHIVO = "La lista de estaciones sin arribos no está disponible en este trabajo."
MOTIVO_SIN_AMPLIACION = "La ampliación contra la base no está disponible para este evento."
CERCA_KM = 50.0

COLUMNAS_ARRIBO = [
    ("fase", "Fase"),
    ("llegada", "Llegada"),
    ("loc", "Loc"),
    ("cha", "Canal"),
    ("residual", "Resid. (s)"),
    ("azimut", "Azimut (°)"),
    ("distancia", "Dist. (°)"),
    ("usada", "Usada"),
    ("modo", "Tipo"),
    ("pick_autor", "Autor"),
    ("pick_metodo", "Método"),
    ("pick_agencia", "Agencia"),
    ("peso", "Peso"),
    ("snr", "SNR"),
    ("magnitud", "Mag. est."),
    ("tipo_magnitud", "Tipo mag."),
    ("residuo_magnitud", "Resid. mag."),
    ("qc", "QC"),
    ("lugar", "Lugar"),
    ("elevacion", "Elev. (m)"),
]

COLUMNAS_SIN_ARRIBOS = [
    ("distancia_km", "Dist. (km)"),
    ("red", "Red"),
    ("estacion", "Estación"),
    ("loc_ref", "Loc ref."),
    ("cha_ref", "Canal ref."),
    ("stream_ref", "Streams"),
    ("evidencia", "Evidencia"),
    ("formas_onda", "Formas de onda"),
    ("cobertura", "Cobertura"),
    ("disponible", "Disp. no usada"),
    ("actividad_ventana", "Actividad ±2 h"),
    ("elevacion", "Elev. (m)"),
    ("lugar", "Lugar"),
    ("pais", "País"),
]

# La tabla muestra solo el stream de referencia; el CSV conserva la lista
# completa para no perder información.
COLUMNAS_SIN_ARRIBOS_CSV = [
    ("streams_vigentes", "Streams vigentes")
    if clave == "stream_ref"
    else (clave, titulo)
    for clave, titulo in COLUMNAS_SIN_ARRIBOS
]

MODO_PICK = {
    "manual": "Manual",
    "automatic": "Automático",
    "auto": "Automático",
}

CALIDAD_PICK = {
    "aprobado": "Aprobado",
    "rechazado": "Rechazado",
    "sin_evaluar": "Sin evaluar",
    "sin evaluar": "Sin evaluar",
}

CAMPOS_EVENTO = {
    "catalogos": ("Fecha_Hora", "Latitud", "Longitud"),
    "no_publicados": ("Fecha_Hora", "Latitud", "Longitud"),
    "no_actualizados": ("fecha_local", "lat_local", "lon_local"),
    "repetidos": ("fecha_hora", "latitud", "longitud"),
}

def _texto(valor) -> str:
    return "" if valor is None else str(valor).strip()


def _numero(valor):
    try:
        return float(str(valor).strip())
    except (TypeError, ValueError):
        return None


def _numero_texto(valor, decimales: int) -> str:
    numero = _numero(valor)
    if numero is None:
        return ""
    return f"{numero:.{decimales}f}"


def _si_no(valor) -> str:
    if valor is True:
        return "Sí"
    if valor is False:
        return "No"
    return "—"


def _instante(texto):
    if not texto:
        return None
    limpio = " ".join(str(texto).strip().split())
    if limpio.endswith("Z"):
        limpio = limpio[:-1]
    limpio = limpio.replace("T", " ")
    if len(limpio) >= 2 and limpio[-2:] == "60":
        limpio = limpio[:-2] + "59"
    for formato in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ):
        try:
            return datetime.datetime.strptime(limpio, formato)
        except ValueError:
            continue
    return None


def _indice_crudo(fila: dict) -> int | None:
    for clave in ("_indice_crudo", "", "Unnamed: 0"):
        valor = _texto(fila.get(clave))
        if valor.isdigit():
            return int(valor)
    return None


def fuente_de_fila(tabla: str, opcion: str) -> str | None:
    """Fuente local de la fila, o ``None`` si no corresponde revisarla."""
    if tabla == "repetidos":
        if opcion.startswith("publica"):
            return fuentes_manifest.referencia().id
        for fuente in sorted(
            fuentes_manifest.locales(), key=lambda item: len(item.id), reverse=True
        ):
            if opcion == fuente.id or opcion.startswith(f"{fuente.id}_"):
                return fuente.id
        return None
    return opcion if fuentes_manifest.es_local(opcion) else None


def _campos_evento(tabla: str, fila: dict) -> tuple[str, str, str] | None:
    claves = CAMPOS_EVENTO.get(tabla)
    if not claves:
        return None
    return tuple(fila.get(clave, "") for clave in claves)


def _distancia_grados(lat1, lon1, lat2, lon2) -> float | None:
    valores = [_numero(lat1), _numero(lon1), _numero(lat2), _numero(lon2)]
    if any(valor is None for valor in valores):
        return None
    a, b, c, d = valores
    return math.hypot(c - a, d - b)


def _distancia_km(lat1, lon1, lat2, lon2) -> float | None:
    """Distancia epicentro-estación en kilómetros (haversine)."""
    valores = [_numero(lat1), _numero(lon1), _numero(lat2), _numero(lon2)]
    if any(valor is None for valor in valores):
        return None
    a, b, c, d = valores
    phi1, phi2 = math.radians(a), math.radians(c)
    dphi = math.radians(c - a)
    dlambda = math.radians(d - b)
    h = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(h)))


def resolver_evento(
    workspace: Path, source_id: str, tabla: str, fila: dict
) -> dict | None:
    """Evento canónico de la fila, por índice crudo o por tiempo y posición."""
    eventos = canonical.leer_canonico(workspace, source_id)
    if not eventos:
        return None

    indice = _indice_crudo(fila)
    if indice is not None:
        for evento in eventos:
            if evento.get("raw_index") == indice:
                return evento

    for clave in ("id_evento", "source_event_id"):
        valor = _texto(fila.get(clave))
        if valor:
            for evento in eventos:
                if _texto(evento.get("source_event_id")) == valor:
                    return evento

    campos = _campos_evento(tabla, fila)
    if campos is None:
        return None
    fecha, lat, lon = campos
    instante = _instante(fecha)
    candidatos = []
    for evento in eventos:
        otro = _instante(evento.get("event_time"))
        if instante is not None and otro is not None:
            diferencia = abs((otro - instante).total_seconds())
            if diferencia > 2.0:
                continue
        elif instante is not None:
            continue
        else:
            diferencia = 0.0
        distancia = _distancia_grados(
            lat, lon, evento.get("latitude"), evento.get("longitude")
        )
        if distancia is not None and distancia > 0.01:
            continue
        candidatos.append((diferencia + (distancia or 0.0), evento))
    if not candidatos:
        return None
    return min(candidatos, key=lambda item: item[0])[1]


def _coincide(registro: dict, evento: dict) -> bool:
    event_id = _texto(evento.get("event_id"))
    if event_id and _texto(registro.get("event_id")) == event_id:
        return True
    source_event_id = _texto(evento.get("source_event_id"))
    if source_event_id and _texto(registro.get("source_event_id")) == source_event_id:
        return True
    return False


def _fila_arribo(arribo: dict) -> dict:
    modo = _texto(arribo.get("pick_status"))
    qc = _texto(arribo.get("qc"))
    manual = modo.lower() == "manual"
    if manual:
        clase = (
            "pick-manual-usada"
            if arribo.get("is_used_in_solution") is True
            else "pick-manual-sin-usar"
        )
    else:
        clase = ""
    fila = {
        "red": _texto(arribo.get("network")),
        "estacion": _texto(arribo.get("station")),
        "fase": _texto(arribo.get("phase")),
        "llegada": _texto(arribo.get("pick_time")),
        "loc": _texto(arribo.get("location")),
        "cha": _texto(arribo.get("channel")),
        "residual": _numero_texto(arribo.get("residual"), 2),
        "azimut": _numero_texto(arribo.get("azimuth"), 1),
        "distancia": _numero_texto(arribo.get("distance_km"), 2),
        "usada": _si_no(arribo.get("is_used_in_solution")),
        "modo": MODO_PICK.get(modo.lower(), modo),
        "pick_autor": _texto(arribo.get("pick_author")),
        "pick_metodo": _texto(arribo.get("pick_method")),
        "pick_agencia": _texto(arribo.get("pick_agency")),
        "peso": _numero_texto(arribo.get("weight"), 2),
        "snr": _numero_texto(arribo.get("snr"), 1),
        "magnitud": _numero_texto(arribo.get("station_magnitude"), 1),
        "tipo_magnitud": _texto(arribo.get("station_magnitude_type")),
        "residuo_magnitud": _numero_texto(
            arribo.get("station_magnitude_residual"), 2
        ),
        "qc": CALIDAD_PICK.get(qc.lower(), qc),
        "lugar": _texto(arribo.get("station_place")),
        "elevacion": _numero_texto(arribo.get("station_elevation_m"), 0),
        "lat": _numero(arribo.get("station_latitude")),
        "lon": _numero(arribo.get("station_longitude")),
        "_usada": arribo.get("is_used_in_solution"),
        "_azimut": _numero(arribo.get("azimuth")),
        "_clase": clase,
    }
    return fila


def _fila_sin_arribos(registro: dict) -> dict:
    evidencia = _texto(registro.get("evidence")).upper()
    forma = _texto(registro.get("waveform_status")).upper()
    fuente = _texto(registro.get("availability_source")).upper()
    actividad = registro.get("activity_window")
    streams_ids = _texto(registro.get("stream_ids"))
    streams = [item for item in streams_ids.split(";") if item]
    if not streams:
        streams = [
            item for item in _texto(registro.get("streams")).split(";") if item
        ]
    stream_ref = streams[0] if streams else ""
    if forma == availability.ESTADO_CON_DATOS:
        estado = availability.ESTADO_CON_DATOS
        disponible = "Sí"
    elif forma == availability.ESTADO_SIN_DATOS:
        estado = availability.ESTADO_SIN_DATOS
        disponible = "No"
    else:
        estado = availability.ESTADO_NO_CONSULTADO
        disponible = "—"
    formas_onda = availability.texto_formas_onda(estado, fuente)
    if estado == availability.ESTADO_CON_DATOS:
        evidencia_texto = availability.texto_evidencia(estado, fuente, actividad)
    elif evidencia == "INDICIO" or (_numero(actividad) or 0) > 0:
        evidencia_texto = "Indicio (actividad)"
    elif estado == availability.ESTADO_SIN_DATOS or evidencia == "SIN_EVIDENCIA":
        evidencia_texto = "Sin evidencia"
    else:
        evidencia_texto = "Sin consultar"
    cobertura_desde = _texto(registro.get("coverage_from"))
    cobertura_hasta = _texto(registro.get("coverage_to"))
    categoria = availability.categoria_evidencia(estado, evidencia_texto)
    return {
        "red": _texto(registro.get("network")),
        "estacion": _texto(registro.get("station")),
        "distancia_km": _numero_texto(registro.get("distance_km"), 1),
        "radio_km": _numero(registro.get("radio_km")),
        "loc_ref": _texto(registro.get("location")),
        "cha_ref": _texto(registro.get("channel")),
        "streams_vigentes": streams_ids or _texto(registro.get("streams")),
        "stream_ref": stream_ref,
        "streams_ids": streams_ids,
        "evidencia": evidencia_texto,
        "formas_onda": formas_onda,
        "cobertura": (
            f"{cobertura_desde} → {cobertura_hasta}"
            if cobertura_desde or cobertura_hasta
            else ""
        ),
        "cobertura_desde": cobertura_desde,
        "cobertura_hasta": cobertura_hasta,
        "disponible": disponible,
        "actividad_ventana": "" if actividad is None else str(actividad),
        "elevacion": _numero_texto(registro.get("station_elevation_m"), 0),
        "lugar": _texto(registro.get("station_place")),
        "pais": _texto(registro.get("station_country")),
        "lat": _numero(registro.get("station_latitude")),
        "lon": _numero(registro.get("station_longitude")),
        "distancia_num": _numero(registro.get("distance_km")),
        "_distancia": _numero(registro.get("distance_km")),
        "_streams": streams,
        "_estado_disponibilidad": estado,
        "_fuente_disponibilidad": fuente,
        "_stream_disponible": "",
        "_categoria": categoria,
    }


def _agrupar(filas: list[dict]) -> list[dict]:
    grupos: dict[tuple[str, str], list[dict]] = {}
    for fila in filas:
        grupos.setdefault((fila["red"], fila["estacion"]), []).append(fila)
    salida = []
    for clave in sorted(grupos, key=lambda item: (item[1], item[0])):
        integrantes = sorted(
            grupos[clave],
            key=lambda fila: (
                fila["_azimut"] is None,
                fila["_azimut"] if fila["_azimut"] is not None else 0.0,
            ),
        )
        red, estacion = clave
        usadas = sum(1 for fila in integrantes if fila["_usada"] is True)
        no_usadas = sum(1 for fila in integrantes if fila["_usada"] is False)
        salida.append(
            {
                "red": red,
                "estacion": estacion,
                "etiqueta": f"{red} {estacion}".strip() or "Estación sin código",
                "filas": integrantes,
                "usadas": usadas,
                "no_usadas": no_usadas,
                "total": len(integrantes),
            }
        )
    return salida


def _resumen(arribos: list[dict], sin_arribos: list[dict], radio) -> dict:
    estaciones = {(fila["red"], fila["estacion"]) for fila in arribos}
    usadas = sum(1 for fila in arribos if fila["_usada"] is True)
    no_usadas = sum(1 for fila in arribos if fila["_usada"] is False)
    sin_marcar = len(arribos) - usadas - no_usadas
    disponibles = sum(
        1 for fila in sin_arribos if fila.get("disponible_no_usada") is True
    )
    partes = [
        f"{len(arribos)} arribo{'' if len(arribos) == 1 else 's'} "
        f"de {len(estaciones)} estación{'' if len(estaciones) == 1 else 'es'}"
    ]
    if arribos:
        partes.append(f"{usadas} usada{'' if usadas == 1 else 's'}")
        if no_usadas:
            partes.append(f"{no_usadas} sin usar")
        if sin_marcar:
            partes.append(f"{sin_marcar} sin dato de uso")
    texto = " · ".join(partes)

    if sin_arribos:
        if radio is not None:
            distancia = f" dentro de {radio:g} km"
        else:
            distancia = ""
        texto_sin = (
            f"{len(sin_arribos)} estación"
            f"{'' if len(sin_arribos) == 1 else 'es'} sin arribos{distancia}"
        )
        if disponibles:
            texto_sin += (
                f" · {disponibles} disponible"
                f"{'' if disponibles == 1 else 's'} y no usada"
                f"{'' if disponibles == 1 else 's'}"
            )
    else:
        texto_sin = "Sin estaciones sin arribos para este evento."
    return {
        "arribos": len(arribos),
        "estaciones": len(estaciones),
        "usadas": usadas,
        "no_usadas": no_usadas,
        "sin_dato_uso": sin_marcar,
        "sin_arribos": len(sin_arribos),
        "disponibles": disponibles,
        "radio_km": radio,
        "texto": texto,
        "texto_sin_arribos": texto_sin,
    }


def _filtros_sin_arribos(
    filas: list[dict],
    radio_exportado,
    radio_km,
    cerca_km,
    solo_cercanas: bool,
) -> dict:
    """Metadatos de los filtros locales de la tabla de sin arribos."""
    if radio_exportado is not None:
        radio_exportado = _numero(radio_exportado)
    if radio_exportado is None:
        radios = [
            fila.get("radio_km")
            for fila in filas
            if fila.get("radio_km") is not None
        ]
        radio_exportado = max(radios) if radios else None
    try:
        solicitado = float(radio_km) if radio_km is not None else None
    except (TypeError, ValueError):
        solicitado = None
    if solicitado is not None and solicitado <= 0:
        solicitado = None
    radio_limitado = False
    radio_mostrar = solicitado
    if (
        radio_mostrar is not None
        and radio_exportado is not None
        and radio_mostrar > radio_exportado
    ):
        radio_mostrar = radio_exportado
        radio_limitado = True
    if radio_mostrar is None:
        radio_mostrar = radio_exportado
    try:
        cerca = float(cerca_km)
    except (TypeError, ValueError):
        cerca = CERCA_KM
    if cerca <= 0:
        cerca = CERCA_KM

    limite = cerca if solo_cercanas else radio_mostrar

    def _cuenta(limite_valor):
        if limite_valor is None:
            return len(filas)
        return sum(
            1
            for fila in filas
            if fila.get("_distancia") is not None
            and fila["_distancia"] <= limite_valor
        )

    mostradas = _cuenta(limite)
    resaltadas = sum(
        1
        for fila in filas
        if (limite is None or (
            fila.get("_distancia") is not None
            and fila["_distancia"] <= limite
        ))
        and fila.get("_distancia") is not None
        and fila["_distancia"] <= cerca
    )
    total = len(filas)
    if total == 0:
        texto = "Sin estaciones sin arribos para este evento."
    elif solo_cercanas:
        texto = (
            f"Mostrando {mostradas} de {total} estaciones "
            f"(solo ≤ {cerca:g} km) · {resaltadas} resaltadas como cerca."
        )
    elif radio_mostrar is not None:
        texto = (
            f"Mostrando {mostradas} de {total} estaciones "
            f"(≤ {radio_mostrar:g} km) · {resaltadas} resaltadas como cerca "
            f"(≤ {cerca:g} km)."
        )
    else:
        texto = (
            f"Mostrando {mostradas} de {total} estaciones (sin tope) · "
            f"{resaltadas} resaltadas como cerca (≤ {cerca:g} km)."
        )
    return {
        "radio_exportado": radio_exportado,
        "radio_exportado_texto": (
            f"{radio_exportado:g}" if radio_exportado is not None else ""
        ),
        "radio_mostrar": radio_mostrar,
        "radio_mostrar_texto": (
            f"{radio_mostrar:g}" if radio_mostrar is not None else ""
        ),
        "radio_limitado": radio_limitado,
        "cerca_km": cerca,
        "cerca_km_texto": f"{cerca:g}",
        "solo_cercanas": bool(solo_cercanas),
        "mostradas": mostradas,
        "resaltadas": resaltadas,
        "texto_estado": texto,
    }


def _vacio(
    source_id: str,
    *,
    estado: str,
    motivo: str = "",
    evento: dict | None = None,
    tiene_sin_arribos: bool = True,
) -> dict:
    return {
        "fuente": source_id,
        "etiqueta": fuentes_manifest.etiqueta(source_id),
        "estado": estado,
        "motivo": motivo,
        "evento": evento or {},
        "resumen": _resumen([], [], None),
        "grupos": [],
        "sin_arribos": [],
        "columnas_arribos": COLUMNAS_ARRIBO,
        "columnas_sin_arribos": COLUMNAS_SIN_ARRIBOS,
        "tiene_sin_arribos": tiene_sin_arribos,
        "solo_no_usadas": False,
        "solo_disponibles": False,
        "radio_exportado": None,
        "radio_mostrar": None,
        "radio_limitado": False,
        "cerca_km": CERCA_KM,
        "solo_cercanas": False,
        "mostradas": 0,
        "resaltadas": 0,
        "texto_estado": "Sin estaciones sin arribos para este evento.",
        "puede_consultar": False,
        "disponibilidad_consultada": False,
        "aviso_sin_arribos": "",
        "ampliado": None,
        "ampliado_clave": "",
        "ampliado_radio": None,
        "max_estaciones": availability.max_estaciones(),
        "max_streams": availability.max_streams(),
        "consulta_estaciones": 0,
        "consulta_total": 0,
        "consulta_omitidas": 0,
        "consulta_pendientes": 0,
        "consulta_requiere_todas": False,
        "tiene_coordenadas": False,
        "tiene_tiempos": False,
        "estaciones_mapa": [],
        "tiempos_llegada": {},
    }


def _agregar_texto(punto: dict, campo: str, valor: str) -> None:
    """Agrega un valor único a un campo de texto separado por ``; ``."""
    valor = _texto(valor)
    if not valor:
        return
    actual = punto.get(campo, "")
    partes = [parte for parte in actual.split("; ") if parte]
    if valor not in partes:
        partes.append(valor)
    punto[campo] = "; ".join(partes)


RANGO_CATEGORIA = {
    "verificado": 3,
    "indicio": 2,
    "sin_evidencia": 1,
    "normal": 0,
}


def _datos_mapa_tiempos(
    evento: dict | None,
    arribos: list[dict],
    sin_arribos: list[dict],
) -> dict:
    """Datos del mapa de estaciones y de la curva distancia-tiempo.

    Agrupa por estación: una estación con arribos se muestra como arribo y no
    se duplica como estación sin arribos. Las distancias de los arribos se
    calculan por haversine y, si faltan coordenadas, se usa el valor canónico
    en grados.
    """
    event_time = _texto((evento or {}).get("event_time"))
    instante_evento = _instante(event_time)
    if instante_evento is not None:
        event_time = instante_evento.isoformat(sep=" ")
    event_lat = _numero((evento or {}).get("latitude"))
    event_lon = _numero((evento or {}).get("longitude"))

    arribos_tiempo = []
    for fila in arribos:
        lat, lon = fila.get("lat"), fila.get("lon")
        distancia = _distancia_km(event_lat, event_lon, lat, lon)
        if distancia is None:
            grados = _numero(fila.get("distancia"))
            if grados is not None:
                distancia = abs(grados) * 111.19
        segundos = None
        instante_pick = _instante(fila.get("llegada"))
        if instante_evento and instante_pick:
            segundos = (instante_pick - instante_evento).total_seconds()
        if distancia is None and segundos is None:
            continue
        arribos_tiempo.append(
            {
                "red": fila.get("red", ""),
                "estacion": fila.get("estacion", ""),
                "fase": fila.get("fase", ""),
                "llegada": fila.get("llegada", ""),
                "modo": fila.get("modo", ""),
                "usada": fila.get("usada", ""),
                "lat": lat,
                "lon": lon,
                "distancia_km": distancia,
                "segundos": segundos,
            }
        )

    puntos: dict[tuple[str, str], dict] = {}
    arribos_por_clave: dict[tuple[str, str], list[dict]] = {}
    for arribo in arribos_tiempo:
        clave = (arribo["red"], arribo["estacion"])
        arribos_por_clave.setdefault(clave, []).append(arribo)
        if arribo["lat"] is None or arribo["lon"] is None:
            continue
        punto = puntos.get(clave)
        if punto is None:
            punto = {
                "tipo": "arribo",
                "red": arribo["red"],
                "estacion": arribo["estacion"],
                "lat": arribo["lat"],
                "lon": arribo["lon"],
                "distancia_km": arribo["distancia_km"],
                "categoria": "arribo",
                "fase": "",
                "evidencia": "",
                "formas_onda": "",
                "disponible": "",
                "streams": "",
                "fases": [],
            }
            puntos[clave] = punto
        elif punto["distancia_km"] is None and arribo["distancia_km"] is not None:
            punto["distancia_km"] = arribo["distancia_km"]
        punto["fases"].append(
            {
                "fase": arribo["fase"],
                "llegada": arribo["llegada"],
                "segundos": arribo["segundos"],
                "modo": arribo["modo"],
                "usada": arribo["usada"],
            }
        )

    claves_arribo = set(arribos_por_clave)
    for fila in sin_arribos:
        lat, lon = fila.get("lat"), fila.get("lon")
        if lat is None or lon is None:
            continue
        clave = (fila.get("red", ""), fila.get("estacion", ""))
        if clave in claves_arribo:
            if clave not in puntos:
                punto = {
                    "tipo": "arribo",
                    "red": fila.get("red", ""),
                    "estacion": fila.get("estacion", ""),
                    "lat": lat,
                    "lon": lon,
                    "distancia_km": fila.get("distancia_num"),
                    "categoria": "arribo",
                    "fase": "",
                    "evidencia": "",
                    "formas_onda": "",
                    "disponible": "",
                    "streams": "",
                    "fases": [],
                }
                for arribo in arribos_por_clave[clave]:
                    punto["fases"].append(
                        {
                            "fase": arribo["fase"],
                            "llegada": arribo["llegada"],
                            "segundos": arribo["segundos"],
                            "modo": arribo["modo"],
                            "usada": arribo["usada"],
                        }
                    )
                puntos[clave] = punto
            continue
        punto = puntos.get(clave)
        if punto is None:
            punto = {
                "tipo": "sin_arribo",
                "red": fila.get("red", ""),
                "estacion": fila.get("estacion", ""),
                "lat": lat,
                "lon": lon,
                "distancia_km": fila.get("distancia_num"),
                "categoria": fila.get("_categoria", "normal"),
                "fase": "",
                "evidencia": "",
                "formas_onda": "",
                "disponible": "",
                "streams": "",
                "fases": [],
            }
            puntos[clave] = punto
        categoria = fila.get("_categoria", "normal")
        if RANGO_CATEGORIA.get(categoria, 0) > RANGO_CATEGORIA.get(
            punto["categoria"], 0
        ):
            punto["categoria"] = categoria
        if punto["distancia_km"] is None:
            punto["distancia_km"] = fila.get("distancia_num")
        _agregar_texto(punto, "evidencia", fila.get("evidencia", ""))
        _agregar_texto(punto, "formas_onda", fila.get("formas_onda", ""))
        _agregar_texto(punto, "streams", fila.get("streams_ids", ""))
        if fila.get("disponible") == "Sí":
            punto["disponible"] = "Sí"
        elif not punto["disponible"]:
            punto["disponible"] = fila.get("disponible", "")

    for punto in puntos.values():
        if punto["tipo"] != "arribo" or not punto["fases"]:
            continue
        principal = min(
            punto["fases"],
            key=lambda fase: (
                fase["segundos"] is None,
                fase["segundos"] or 0.0,
            ),
        )
        punto["fase"] = principal["fase"]

    estaciones_mapa = sorted(
        puntos.values(),
        key=lambda punto: (
            punto["tipo"] != "arribo",
            punto["distancia_km"] is None,
            punto["distancia_km"] or 0.0,
            punto["estacion"],
        ),
    )

    estaciones_tiempo = []
    vistos_tiempo: set[tuple[str, str]] = set()
    for fila in sin_arribos:
        clave = (fila.get("red", ""), fila.get("estacion", ""))
        if clave in claves_arribo or clave in vistos_tiempo:
            continue
        distancia = fila.get("distancia_num")
        if distancia is None:
            continue
        vistos_tiempo.add(clave)
        estaciones_tiempo.append(
            {
                "red": fila.get("red", ""),
                "estacion": fila.get("estacion", ""),
                "distancia_km": distancia,
                "categoria": fila.get("_categoria", "normal"),
                "evidencia": fila.get("evidencia", ""),
            }
        )
    estaciones_tiempo.sort(key=lambda estacion: estacion["distancia_km"])

    graficables = [
        arribo
        for arribo in arribos_tiempo
        if arribo["distancia_km"] is not None
        and arribo["segundos"] is not None
    ]
    tiene_coordenadas = bool(estaciones_mapa)
    tiene_tiempos = bool(event_time) and bool(graficables or estaciones_tiempo)
    tiempos_llegada = (
        {
            "event_time": event_time,
            "evento": {"lat": event_lat, "lon": event_lon},
            "estaciones": estaciones_tiempo,
            "arribos": arribos_tiempo,
        }
        if tiene_tiempos
        else {}
    )
    return {
        "tiene_coordenadas": tiene_coordenadas,
        "tiene_tiempos": tiene_tiempos,
        "estaciones_mapa": estaciones_mapa,
        "tiempos_llegada": tiempos_llegada,
    }


def revisar_evento(
    workspace: Path,
    source_id: str,
    evento: dict | None,
    *,
    solo_no_usadas: bool = False,
    solo_disponibles: bool = False,
    radio_km: float | None = None,
    cerca_km: float = CERCA_KM,
    solo_cercanas: bool = False,
    ampliado: str | None = None,
) -> dict:
    """Arma la revisión de un evento para una fuente local."""
    capacidades = fuentes_manifest.capacidades(source_id)
    if "arribos" not in capacidades:
        return None  # type: ignore[return-value]
    if ampliado and "inventario" not in capacidades:
        return None  # type: ignore[return-value]
    tiene_sin_arribos = "inventario" in capacidades
    puede_consultar_base = (
        "disponibilidad_ondas" in capacidades and availability.configurada()
    )

    ruta_arribos = canonical.ruta_arribos(workspace, source_id)
    meta = canonical.leer_meta(workspace, source_id)
    presentes = (meta or {}).get("extensions", {}).get("arribos", {})
    hay_arribos = ruta_arribos.is_file() or bool(presentes.get("present"))
    if ampliado is None and not hay_arribos:
        return _vacio(
            source_id,
            estado="no_evaluable",
            motivo=MOTIVO_SIN_REVISION,
            evento=evento,
            tiene_sin_arribos=tiene_sin_arribos,
        )
    if evento is None:
        return _vacio(
            source_id,
            estado="no_evaluable",
            motivo=MOTIVO_EVENTO,
            tiene_sin_arribos=tiene_sin_arribos,
        )

    event_id = str((evento or {}).get("event_id") or "")
    arribos = [
        _fila_arribo(registro)
        for registro in canonical.leer_arribos(workspace, source_id)
        if _coincide(registro, evento)
    ]
    sin_arribos: list[dict] = []
    aviso = ""
    radio = (meta or {}).get("station_radius_km")

    if ampliado:
        registros = amplification.leer_ampliacion(
            workspace, source_id, event_id, ampliado
        )
        if not registros:
            return _vacio(
                source_id,
                estado="no_evaluable",
                motivo=MOTIVO_SIN_AMPLIACION,
                evento=evento,
                tiene_sin_arribos=True,
            )
        sin_arribos = [_fila_sin_arribos(registro) for registro in registros]
        sin_arribos.sort(
            key=lambda fila: (
                fila["_distancia"] is None,
                fila["_distancia"] if fila["_distancia"] is not None else 0.0,
            )
        )
        aviso = "Vista ampliada contra la base de SeisComp."
        radios = [
            registro.get("radio_km")
            for registro in registros
            if registro.get("radio_km") is not None
        ]
        radio = max(radios) if radios else None
        tiene_sin_arribos = True
    elif tiene_sin_arribos:
        ruta_sin = canonical.ruta_estaciones_sin_arribos(workspace, source_id)
        estado_sin = (meta or {}).get("extensions", {}).get(
            "estaciones_sin_arribos", {}
        )
        hay_sin = ruta_sin.is_file() or bool(estado_sin.get("present"))
        if hay_sin:
            sin_arribos = [
                _fila_sin_arribos(registro)
                for registro in canonical.leer_estaciones_sin_arribos(
                    workspace, source_id
                )
                if _coincide(registro, evento)
            ]
            sin_arribos.sort(
                key=lambda fila: (
                    fila["_distancia"] is None,
                    fila["_distancia"] if fila["_distancia"] is not None else 0.0,
                )
            )
        else:
            aviso = MOTIVO_SIN_ARCHIVO

    cache: dict = {}
    if sin_arribos and event_id:
        cache = availability.leer_cache(workspace, source_id, event_id)
        if cache:
            availability.aplicar_cache(sin_arribos, cache)
    puede_consultar = puede_consultar_base and any(
        fila.get("_streams") for fila in sin_arribos
    )
    arribos_mapa = list(arribos)
    sin_arribos_mapa = list(sin_arribos)
    if solo_disponibles:
        sin_arribos = [
            fila for fila in sin_arribos if fila.get("disponible_no_usada") is True
        ]
    if solo_no_usadas:
        arribos = [fila for fila in arribos if fila["_usada"] is False]

    filtros = _filtros_sin_arribos(
        sin_arribos, radio, radio_km, cerca_km, solo_cercanas
    )
    max_est = availability.max_estaciones()
    max_str = availability.max_streams()
    seleccionadas, consulta_total, consulta_omitidas = (
        seleccionar_disponibilidad(
            sin_arribos,
            radio_km=filtros["radio_mostrar"],
            cerca_km=filtros["cerca_km"],
            solo_cercanas=filtros["solo_cercanas"],
            todas=False,
            max_estaciones=max_est,
            max_streams=max_str,
        )
    )
    consulta_pendientes = sum(
        1
        for fila in sin_arribos
        if fila.get("_estado_disponibilidad")
        == availability.ESTADO_NO_CONSULTADO
    )
    datos_mapa = _datos_mapa_tiempos(
        evento, arribos_mapa, sin_arribos_mapa
    )
    return {
        "fuente": source_id,
        "etiqueta": fuentes_manifest.etiqueta(source_id),
        "estado": "ok",
        "motivo": "",
        "evento": evento,
        "resumen": _resumen(
            arribos, sin_arribos, filtros["radio_exportado"]
        ),
        "grupos": _agrupar(arribos),
        "sin_arribos": sin_arribos,
        "columnas_arribos": COLUMNAS_ARRIBO,
        "columnas_sin_arribos": COLUMNAS_SIN_ARRIBOS,
        "tiene_sin_arribos": tiene_sin_arribos,
        "solo_no_usadas": bool(solo_no_usadas),
        "solo_disponibles": bool(solo_disponibles),
        "puede_consultar": puede_consultar,
        "disponibilidad_consultada": bool(cache),
        "aviso_sin_arribos": aviso,
        "ampliado": ampliado,
        "ampliado_clave": ampliado or "",
        "ampliado_radio": radio if ampliado else None,
        "max_estaciones": max_est,
        "max_streams": max_str,
        "consulta_estaciones": len(seleccionadas),
        "consulta_total": consulta_total,
        "consulta_omitidas": consulta_omitidas,
        "consulta_pendientes": consulta_pendientes,
        "consulta_requiere_todas": consulta_omitidas > 0,
        "tiene_coordenadas": datos_mapa["tiene_coordenadas"],
        "tiene_tiempos": datos_mapa["tiene_tiempos"],
        "estaciones_mapa": datos_mapa["estaciones_mapa"],
        "tiempos_llegada": datos_mapa["tiempos_llegada"],
        **filtros,
    }


def revisar_fila(
    workspace: Path,
    tabla: str,
    opcion: str,
    fila: dict,
    *,
    solo_no_usadas: bool = False,
    solo_disponibles: bool = False,
    radio_km: float | None = None,
    cerca_km: float = CERCA_KM,
    solo_cercanas: bool = False,
    ampliado: str | None = None,
) -> dict | None:
    """Revisión para una fila de detalle, o ``None`` si no se debe mostrar."""
    source_id = fuente_de_fila(tabla, opcion)
    if source_id is None:
        return None
    if "arribos" not in fuentes_manifest.capacidades(source_id):
        return None
    evento = resolver_evento(workspace, source_id, tabla, fila)
    return revisar_evento(
        workspace,
        source_id,
        evento,
        solo_no_usadas=solo_no_usadas,
        solo_disponibles=solo_disponibles,
        radio_km=radio_km,
        cerca_km=cerca_km,
        solo_cercanas=solo_cercanas,
        ampliado=ampliado,
    )


def filas_visibles(
    filas: list[dict],
    radio_km: float | None = None,
    cerca_km: float = CERCA_KM,
    solo_cercanas: bool = False,
) -> list[dict]:
    """Filas que quedan visibles con los filtros de radio y cercanía."""
    limite = cerca_km if solo_cercanas else radio_km
    if limite is None:
        return list(filas)
    return [
        fila
        for fila in filas
        if fila.get("_distancia") is not None
        and fila["_distancia"] <= limite
    ]


def seleccionar_disponibilidad(
    filas: list[dict],
    *,
    radio_km: float | None = None,
    cerca_km: float = CERCA_KM,
    solo_cercanas: bool = False,
    todas: bool = False,
    max_estaciones: int = 150,
    max_streams: int = 5000,
) -> tuple[list[dict], int, int]:
    """Selecciona las estaciones a consultar, priorizando las más cercanas.

    Devuelve (seleccionadas, total_visibles, omitidas). Sin ``todas`` se corta
    en ``max_estaciones``; en ambos casos se respeta ``max_streams``.
    """
    visibles = filas_visibles(
        filas,
        radio_km=radio_km,
        cerca_km=cerca_km,
        solo_cercanas=solo_cercanas,
    )
    ordenadas = sorted(
        visibles,
        key=lambda fila: (
            fila.get("_distancia") is None,
            fila.get("_distancia")
            if fila.get("_distancia") is not None
            else 0.0,
        ),
    )
    seleccionadas = []
    vistos: set[str] = set()
    for fila in ordenadas:
        if not todas and len(seleccionadas) >= max_estaciones:
            break
        nuevos = [
            stream
            for stream in fila.get("_streams", [])
            if stream and stream not in vistos
        ]
        if len(vistos) + len(nuevos) > max_streams:
            break
        seleccionadas.append(fila)
        vistos.update(nuevos)
    return seleccionadas, len(visibles), len(visibles) - len(seleccionadas)


def filas_para_csv(revision: dict, tipo: str) -> tuple[list[str], list[list[str]]]:
    """Cabecera y filas de una extensión, listas para exportar."""
    if tipo == "arribos":
        columnas = [("red", "Red"), ("estacion", "Estación")] + list(
            revision["columnas_arribos"]
        )
        filas = [
            fila
            for grupo in revision.get("grupos", [])
            for fila in grupo.get("filas", [])
        ]
    else:
        columnas = COLUMNAS_SIN_ARRIBOS_CSV
        filas = revision.get("sin_arribos", [])
    return [titulo for _clave, titulo in columnas], [
        [str(fila.get(clave, "")) for clave, _titulo in columnas] for fila in filas
    ]
