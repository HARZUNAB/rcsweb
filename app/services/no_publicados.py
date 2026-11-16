"""Coincidencias de un evento no publicado en las demás fuentes locales.

La fuente local no publica por sí sola: el cruce con Eventquery es la
estimación de publicación. Para un evento que no cruzó, este módulo busca si
existe en otras fuentes locales y muestra, para cada una, si el evento existe y
si esa solución tiene cruce con Eventquery.
"""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

from ..domain.catalogs import canonical
from ..domain.catalogs import manifest as fuentes_manifest
from . import indicios

VENTANA_CONFIRMACION_SEG = 6.0
TOLERANCIA_CONFIRMACION_GRADOS = 0.5
VENTANA_REVISION_SEG = 120.0
TOLERANCIA_REVISION_GRADOS = 2.0

ESTADOS = {
    "con_cruce": "Con cruce Eventquery",
    "sin_cruce": "Sin cruce Eventquery",
    "sin_evaluar": "Sin evaluar",
    "ambiguo": "Ambiguo",
    "candidato": "Candidato",
    "sin_coincidencia": "Sin coincidencia",
}


def _instante(valor) -> datetime | None:
    texto = " ".join(str(valor or "").strip().split())
    if not texto:
        return None
    if texto[-2:] == "60":
        texto = texto[:-2] + "59"
    for formato in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(texto, formato)
        except ValueError:
            continue
    try:
        return datetime.strptime(texto[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _numero(valor) -> float | None:
    try:
        return float(str(valor).strip())
    except (TypeError, ValueError):
        return None


def _distancia_km(lat1, lon1, lat2, lon2) -> float | None:
    if None in (lat1, lon1, lat2, lon2):
        return None
    radio = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * radio * math.asin(min(1.0, math.sqrt(a)))


def _candidatos(
    fila: dict,
    eventos: list[dict],
    ventana_seg: float,
    tolerancia_grados: float,
) -> list[dict]:
    instante = _instante(fila.get("Fecha_Hora"))
    lat = _numero(fila.get("Latitud"))
    lon = _numero(fila.get("Longitud"))
    if instante is None or lat is None or lon is None:
        return []
    candidatos = []
    for evento in eventos:
        otro_instante = _instante(evento.get("event_time"))
        otra_lat = _numero(evento.get("latitude"))
        otra_lon = _numero(evento.get("longitude"))
        if otro_instante is None or otra_lat is None or otra_lon is None:
            continue
        dt_seg = abs((otro_instante - instante).total_seconds())
        if dt_seg > ventana_seg:
            continue
        if (
            abs(otra_lat - lat) > tolerancia_grados
            or abs(otra_lon - lon) > tolerancia_grados
        ):
            continue
        candidatos.append(
            {
                "evento": evento,
                "dt_seg": dt_seg,
                "dist_km": _distancia_km(lat, lon, otra_lat, otra_lon),
            }
        )
    candidatos.sort(
        key=lambda item: (
            item["dt_seg"],
            item["dist_km"] if item["dist_km"] is not None else float("inf"),
        )
    )
    return candidatos


def _resumen_fuente(
    workspace: Path,
    fuente: str,
    fila: dict,
    indice_cruces,
) -> dict:
    definicion = fuentes_manifest.por_id(fuente)
    etiqueta = fuentes_manifest.etiqueta(fuente)
    derivada = bool(definicion and definicion.derived)
    eventos = canonical.leer_canonico(workspace, fuente)
    confirmados = _candidatos(
        fila,
        eventos,
        VENTANA_CONFIRMACION_SEG,
        TOLERANCIA_CONFIRMACION_GRADOS,
    )
    revision = _candidatos(
        fila,
        eventos,
        VENTANA_REVISION_SEG,
        TOLERANCIA_REVISION_GRADOS,
    )
    candidatos = confirmados or revision
    elegido = candidatos[0] if candidatos else None
    cruce = None
    if elegido is not None and not derivada:
        cruce = indicios.estado_cruce_eventquery(
            workspace,
            fuente,
            elegido["evento"],
            indice=indice_cruces,
        )

    if not revision:
        estado = "sin_coincidencia"
    elif len(confirmados) > 1:
        estado = "ambiguo"
    elif len(confirmados) == 1:
        if derivada:
            estado = "sin_evaluar"
        else:
            estado = (
                "con_cruce"
                if cruce is True
                else ("sin_cruce" if cruce is False else "sin_evaluar")
            )
    elif len(revision) > 1:
        estado = "ambiguo"
    else:
        estado = "candidato"

    return {
        "fuente": fuente,
        "etiqueta": etiqueta,
        "derived": derivada,
        "existe": bool(revision),
        "estado": estado,
        "estado_texto": ESTADOS.get(estado, estado),
        "n_candidatos": len(candidatos),
        "evento": elegido["evento"] if elegido else None,
        "dt_seg": round(elegido["dt_seg"], 1) if elegido else None,
        "dist_km": (
            round(elegido["dist_km"], 1)
            if elegido and elegido["dist_km"] is not None
            else None
        ),
        "analista": (
            elegido["evento"].get("analyst", "") if elegido else ""
        ),
        "cruce_eventquery": cruce,
    }


def coincidencias(
    workspace: Path,
    fuente: str,
    fila: dict,
    otras_fuentes: list[str],
) -> dict:
    """Coincidencias del evento en todas las demás fuentes locales."""
    workspace = Path(workspace)
    resultados = []
    for otra in otras_fuentes:
        if otra == fuente:
            continue
        indice = (
            None
            if fuentes_manifest.por_id(otra)
            and fuentes_manifest.por_id(otra).derived
            else indicios.indice_cruces_eventquery(workspace, otra)
        )
        resultados.append(_resumen_fuente(workspace, otra, fila, indice))

    con_evento = [item for item in resultados if item["existe"]]
    con_evento_no_derivadas = [
        item for item in con_evento if not item["derived"]
    ]
    con_cruce = [
        item
        for item in con_evento_no_derivadas
        if item["estado"] == "con_cruce"
    ]
    if con_cruce:
        estado_general = "con_cruce"
    elif con_evento_no_derivadas:
        estado_general = "sin_cruce"
    elif con_evento:
        estado_general = "sin_evaluar"
    else:
        estado_general = "sin_coincidencia"
    return {
        "estado": estado_general,
        "fuentes": resultados,
        "fuentes_con_evento": [item["etiqueta"] for item in con_evento],
        "fuentes_con_evento_no_derivadas": [
            item["etiqueta"] for item in con_evento_no_derivadas
        ],
        "fuentes_con_cruce": [item["etiqueta"] for item in con_cruce],
    }
