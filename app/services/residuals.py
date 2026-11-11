"""Enriquecimiento temporal de residuales desde fuentes locales.

La base Central no guarda el residual de sus picks. Este servicio copia, solo
para el trabajo actual, el residual de un pick equivalente de otra fuente local
que sí lo tenga. No modifica la base de origen ni el contrato canónico: llena
``ArriboCanonico.residual`` en el ``arribos.jsonl`` del trabajo y deja la
procedencia en ``raw``.

El emparejamiento es deliberadamente estricto:

- evento: ±2 s y ±5 km;
- pick: misma estación, misma fase P/S y ±0,5 s;
- se prefiere la fuente cuyo sistema coincide con el ``database`` del arribo.
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from ..domain.catalogs import canonical
from ..domain.catalogs import manifest as fuentes_manifest

LOG = logging.getLogger(__name__)

TOL_EVENTO_S = 2.0
TOL_EVENTO_KM = 5.0
TOL_PICK_S = 0.5


def _texto(valor) -> str:
    return "" if valor is None else str(valor).strip()


def _numero(valor) -> float | None:
    try:
        return float(str(valor).strip())
    except (TypeError, ValueError):
        return None


def _instante(texto) -> datetime | None:
    limpio = " ".join(str(texto or "").strip().replace("Z", "").split())
    if not limpio:
        return None
    for formato in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(limpio, formato)
        except ValueError:
            continue
    return None


def _distancia_km(lat1, lon1, lat2, lon2) -> float | None:
    valores = [_numero(lat1), _numero(lon1), _numero(lat2), _numero(lon2)]
    if any(valor is None for valor in valores):
        return None
    a, b, c, d = valores
    radio = 6371.0088
    phi1, phi2 = math.radians(a), math.radians(c)
    dphi = math.radians(c - a)
    dlambda = math.radians(d - b)
    h = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * radio * math.asin(min(1.0, math.sqrt(h)))


def _sistema(valor) -> str:
    """Normaliza el sistema de procesamiento: ``Seisan_v9.1`` → ``seisan``."""
    texto = _texto(valor).lower()
    partes = re.split(r"[^a-z]+", texto)
    return partes[0] if partes and partes[0] else texto


def _grupo_fase(valor) -> str:
    token = _texto(valor).upper()
    return token[:1] if token[:1] in ("P", "S") else ""


def _clave_pick(arribo: dict) -> tuple[str, str]:
    return (
        _texto(arribo.get("station")).upper(),
        _grupo_fase(arribo.get("phase")),
    )


def _indice_picks(arribos: list[dict]) -> dict[tuple[str, str], list[tuple[datetime, dict]]]:
    indice: dict[tuple[str, str], list[tuple[datetime, dict]]] = defaultdict(list)
    for arribo in arribos:
        if arribo.get("residual") is None:
            continue
        clave = _clave_pick(arribo)
        if not clave[0] or not clave[1]:
            continue
        instante = _instante(arribo.get("pick_time"))
        if instante is None:
            continue
        indice[clave].append((instante, arribo))
    for lista in indice.values():
        lista.sort(key=lambda item: item[0])
    return indice


def _donantes(workspace: Path, fuentes) -> list[dict]:
    donantes: list[dict] = []
    for fuente in fuentes:
        arribos = canonical.leer_arribos(workspace, fuente.id)
        if not any(arribo.get("residual") is not None for arribo in arribos):
            continue
        por_evento: dict[str, list[dict]] = defaultdict(list)
        for arribo in arribos:
            por_evento[_texto(arribo.get("event_id"))].append(arribo)
        for evento in canonical.leer_canonico(workspace, fuente.id):
            instante = _instante(evento.get("event_time"))
            lat = _numero(evento.get("latitude"))
            lon = _numero(evento.get("longitude"))
            if instante is None or lat is None or lon is None:
                continue
            indice = _indice_picks(por_evento.get(_texto(evento.get("event_id")), []))
            if not indice:
                continue
            donantes.append(
                {
                    "source_id": fuente.id,
                    "event_id": _texto(evento.get("event_id")),
                    "instante": instante,
                    "lat": lat,
                    "lon": lon,
                    "indice": indice,
                }
            )
    return donantes


def _evento_cercano(
    donante: dict, instante: datetime, lat: float, lon: float
) -> bool:
    if abs((donante["instante"] - instante).total_seconds()) > TOL_EVENTO_S:
        return False
    distancia = _distancia_km(lat, lon, donante["lat"], donante["lon"])
    return distancia is not None and distancia <= TOL_EVENTO_KM


def _mejor_pick(
    arribo: dict,
    instante: datetime,
    candidatos_evento: list[dict],
) -> tuple[dict, dict, float, bool] | None:
    clave = _clave_pick(arribo)
    if not clave[0] or not clave[1]:
        return None
    sistema_objetivo = _sistema(arribo.get("database"))
    mejores = []
    for donante in candidatos_evento:
        for instante_pick, pick in donante["indice"].get(clave, []):
            diferencia = abs((instante_pick - instante).total_seconds())
            if diferencia > TOL_PICK_S:
                continue
            mismo_sistema = bool(
                sistema_objetivo
                and sistema_objetivo == _sistema(pick.get("database"))
            )
            mejores.append(
                (
                    not mismo_sistema,
                    diferencia,
                    donante["source_id"],
                    donante,
                    pick,
                )
            )
    if not mejores:
        return None
    elegido = min(mejores, key=lambda item: (item[0], item[1], item[2]))
    _, diferencia, _, donante, pick = elegido
    return donante, pick, diferencia, not elegido[0]


def enriquecer_residuales(workspace: Path) -> dict[str, int]:
    """Completa los residuales faltantes de cada fuente desde las demás.

    Devuelve cuántos arribos se enriquecieron por fuente. Es best-effort: si no
    hay una fuente donante o un pick equivalente, el residual queda vacío.
    """
    fuentes = [
        fuente
        for fuente in fuentes_manifest.fuentes()
        if "arribos" in fuente.capacidades
    ]
    if len(fuentes) < 2:
        return {}
    donantes = _donantes(workspace, fuentes)
    if not donantes:
        return {}

    resultado: dict[str, int] = {}
    for objetivo in fuentes:
        arribos = canonical.leer_arribos(workspace, objetivo.id)
        if not any(arribo.get("residual") is None for arribo in arribos):
            continue
        por_evento: dict[str, list[dict]] = defaultdict(list)
        for arribo in arribos:
            por_evento[_texto(arribo.get("event_id"))].append(arribo)
        enriquecidos = 0
        for evento in canonical.leer_canonico(workspace, objetivo.id):
            instante = _instante(evento.get("event_time"))
            lat = _numero(evento.get("latitude"))
            lon = _numero(evento.get("longitude"))
            if instante is None or lat is None or lon is None:
                continue
            candidatos_evento = [
                donante
                for donante in donantes
                if donante["source_id"] != objetivo.id
                and _evento_cercano(donante, instante, lat, lon)
            ]
            if not candidatos_evento:
                continue
            for arribo in por_evento.get(_texto(evento.get("event_id")), []):
                if arribo.get("residual") is not None:
                    continue
                instante_pick = _instante(arribo.get("pick_time"))
                if instante_pick is None:
                    continue
                elegido = _mejor_pick(arribo, instante_pick, candidatos_evento)
                if elegido is None:
                    continue
                donante, pick, diferencia, mismo_sistema = elegido
                raw = dict(arribo.get("raw") or {})
                raw["residual_fuente"] = donante["source_id"]
                raw["residual_evento"] = donante["event_id"]
                raw["residual_pick"] = _texto(pick.get("pick_id"))
                raw["residual_dt"] = round(diferencia, 3)
                raw["residual_mismo_sistema"] = mismo_sistema
                arribo["raw"] = raw
                arribo["residual"] = pick.get("residual")
                enriquecidos += 1
        if not enriquecidos:
            continue
        resultado[objetivo.id] = enriquecidos
        ruta = canonical.ruta_arribos(workspace, objetivo.id)
        temporal = ruta.with_suffix(ruta.suffix + ".tmp")
        with temporal.open("w", encoding="utf-8") as archivo:
            for arribo in arribos:
                archivo.write(json.dumps(arribo, ensure_ascii=False) + "\n")
        temporal.replace(ruta)
        LOG.info(
            "Residuales: %s arribos enriquecidos desde fuentes locales.",
            enriquecidos,
        )
    return resultado


def hay_residuales_por_enriquecer(workspace: Path) -> bool:
    """Indica si hay una fuente con residuales faltantes y otra con residuales."""
    fuentes = [
        fuente
        for fuente in fuentes_manifest.fuentes()
        if "arribos" in fuente.capacidades
    ]
    if len(fuentes) < 2:
        return False
    hay_faltantes = False
    hay_donante = False
    for fuente in fuentes:
        for arribo in canonical.leer_arribos(workspace, fuente.id):
            if arribo.get("residual") is None:
                hay_faltantes = True
            else:
                hay_donante = True
            if hay_faltantes and hay_donante:
                return True
    return False
