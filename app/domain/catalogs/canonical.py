"""Escritura y lectura del catálogo canónico en JSON Lines.

El pipeline del core sigue usando CSV planos; este módulo los traduce al
contrato canónico para que la app y las extensiones no dependan del formato de
entrada.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .schema import SCHEMA_VERSION, EventoCanonico


def _numero(texto):
    try:
        return float(str(texto).strip())
    except (TypeError, ValueError):
        return None


def ruta_canonica(workspace: Path, source_id: str) -> Path:
    return workspace / "catalogo" / source_id / "eventos.jsonl"


def escribir_desde_csv(
    workspace: Path,
    source_id: str,
    formato: str,
    ruta_csv: Path,
) -> Path:
    """Convierte un CSV plano normalizado al catálogo canónico JSONL."""
    destino = ruta_canonica(workspace, source_id)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with ruta_csv.open(encoding="utf-8-sig", newline="") as archivo:
        lector = csv.DictReader(archivo)
        with destino.open("w", encoding="utf-8") as salida:
            for indice, fila in enumerate(lector):
                evento = EventoCanonico(
                    source_id=source_id,
                    event_id=f"{source_id}:{indice:06d}",
                    event_time=fila.get("Fecha_Hora") or None,
                    latitude=_numero(fila.get("Latitud")),
                    longitude=_numero(fila.get("Longitud")),
                    depth_km=_numero(fila.get("Prof.")),
                    magnitude=_numero(fila.get("Mag.")),
                    magnitude_type=fila.get("Tipo_mag.", "") or "",
                    agency=source_id,
                    analyst=fila.get("Analista", "") or "",
                    status="published" if formato == "eventquery" else "reported",
                    is_preferred=True,
                    is_published=formato == "eventquery",
                    raw=dict(fila),
                )
                salida.write(json.dumps(evento.to_dict(), ensure_ascii=False) + "\n")
    return destino


def leer_canonico(workspace: Path, source_id: str) -> list[dict]:
    ruta = ruta_canonica(workspace, source_id)
    if not ruta.is_file():
        return []
    eventos = []
    with ruta.open(encoding="utf-8") as archivo:
        for linea in archivo:
            if linea.strip():
                eventos.append(json.loads(linea))
    return eventos


def version() -> str:
    return SCHEMA_VERSION
