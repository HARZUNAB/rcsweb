"""Resolución de referencias Eventquery a sus soluciones locales.

Eventquery no tiene fases. Para evaluar un publicado se buscan las soluciones
locales que cruzaron con esa fila y se calcula su Wadati.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from ..domain.catalogs import canonical
from ..domain.catalogs import manifest as fuentes_manifest
from . import station_review, wadati
from .analysts import normalizar_nombre


def _texto(valor) -> str:
    return "" if valor is None else str(valor).strip()


def _numero(valor) -> float | None:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return numero


def _clave_tiempo(valor) -> str:
    return " ".join(
        _texto(valor).replace("T", " ").replace("Z", " ").split()
    )


def _instante(valor) -> datetime | None:
    clave = _clave_tiempo(valor)
    if not clave:
        return None
    try:
        return datetime.fromisoformat(clave.replace(" ", "T", 1))
    except ValueError:
        return None


def _fuente(source_id: str):
    fuente = fuentes_manifest.por_id(source_id)
    if fuente is None or fuente.derived:
        return None
    return fuente


def _buscar_evento(
    eventos: list[dict],
    fecha_local: str,
    lat_local: float | None,
    lon_local: float | None,
) -> dict | None:
    clave = _clave_tiempo(fecha_local)

    def distancia(evento: dict) -> float:
        lat = _numero(evento.get("latitude"))
        lon = _numero(evento.get("longitude"))
        if (
            lat is None
            or lon is None
            or lat_local is None
            or lon_local is None
        ):
            return 0.0
        return abs(lat - lat_local) + abs(lon - lon_local)

    exactos = [
        evento
        for evento in eventos
        if _clave_tiempo(evento.get("event_time")) == clave
    ]
    if exactos:
        return min(exactos, key=distancia)

    objetivo = _instante(fecha_local)
    if objetivo is None:
        return None
    cercanos = []
    for evento in eventos:
        instante = _instante(evento.get("event_time"))
        if instante is None:
            continue
        diferencia = abs((instante - objetivo).total_seconds())
        if diferencia > 3.0:
            continue
        if (
            lat_local is not None
            and lon_local is not None
            and (
                _numero(evento.get("latitude")) is None
                or _numero(evento.get("longitude")) is None
            )
        ):
            continue
        if distancia(evento) > 0.02:
            continue
        cercanos.append((diferencia, distancia(evento), evento))
    if not cercanos:
        return None
    return min(cercanos, key=lambda item: (item[0], item[1]))[2]


def _probable(
    analista_probable: str, fuente: str, analista: str
) -> bool:
    texto = _texto(analista_probable).lower()
    if not texto:
        return False
    etiqueta = _texto(fuentes_manifest.etiqueta(fuente)).lower()
    analista_norm = normalizar_nombre(analista)
    texto_norm = normalizar_nombre(texto)
    if etiqueta and etiqueta in texto:
        if not analista_norm:
            return True
        return analista_norm in texto_norm
    return bool(analista_norm and analista_norm in texto_norm)


def soluciones_locales(
    workspace: Path,
    n_fila_eventquery: int,
    analista_probable: str = "",
) -> list[dict]:
    """Soluciones locales que cruzaron con una fila de Eventquery."""
    workspace = Path(workspace)
    objetivo = str(n_fila_eventquery)
    carpeta = workspace / "datos"
    if not carpeta.is_dir():
        return []

    cache_eventos: dict[str, list[dict]] = {}
    candidatos: list[dict] = []
    for ruta in sorted(carpeta.glob("atribucion_*.csv")):
        source_id = ruta.stem.removeprefix("atribucion_")
        if _fuente(source_id) is None:
            continue
        try:
            with ruta.open(encoding="utf-8-sig", newline="") as archivo:
                for fila in csv.DictReader(archivo):
                    if (
                        _texto(fila.get("n_fila_eventquery"))
                        != objetivo
                    ):
                        continue
                    fuente = _texto(fila.get("fuente")) or source_id
                    if _fuente(fuente) is None:
                        continue
                    if fuente not in cache_eventos:
                        cache_eventos[fuente] = canonical.leer_canonico(
                            workspace, fuente
                        )
                    fecha_local = _texto(fila.get("fecha_local"))
                    lat_local = _numero(fila.get("lat_local"))
                    lon_local = _numero(fila.get("lon_local"))
                    evento = _buscar_evento(
                        cache_eventos[fuente],
                        fecha_local,
                        lat_local,
                        lon_local,
                    )
                    analista = _texto(fila.get("analista"))
                    if evento is not None:
                        revision = (
                            station_review.revisar_evento(
                                workspace, fuente, evento
                            )
                            or {}
                        )
                        datos_wadati = (
                            revision.get("wadati") or wadati.analizar([])
                        )
                        evento_local = _texto(evento.get("event_id"))
                        fila_local = evento.get("raw_index")
                        event_time = _texto(evento.get("event_time"))
                    else:
                        datos_wadati = wadati.analizar([])
                        evento_local = ""
                        fila_local = None
                        event_time = fecha_local
                    candidatos.append(
                        {
                            "fuente": fuente,
                            "fuente_etiqueta": fuentes_manifest.etiqueta(
                                fuente
                            ),
                            "evento_local": evento_local,
                            "fila_local": fila_local,
                            "event_time": event_time,
                            "analista": analista
                            or (
                                _texto(evento.get("analyst"))
                                if evento
                                else ""
                            ),
                            "dt_seg": _numero(fila.get("dt_seg")),
                            "dist_km": _numero(fila.get("dist_km")),
                            "probable": _probable(
                                analista_probable,
                                fuente,
                                analista,
                            ),
                            "wadati": datos_wadati,
                        }
                    )
        except OSError:
            continue

    candidatos.sort(
        key=lambda item: (
            not item["probable"],
            item["dist_km"]
            if item["dist_km"] is not None
            else 1e9,
            item["dt_seg"]
            if item["dt_seg"] is not None
            else 1e9,
            item["fuente"],
            item["evento_local"],
        )
    )
    return candidatos
