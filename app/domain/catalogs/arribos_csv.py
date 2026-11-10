"""Interfaz CSV de la extensión canónica de arribos.

Los adaptadores escriben este archivo y ``canonical._extension_arribos`` lo
convierte al contrato. Las columnas son las que ya existen en el contrato; las
columnas extra se conservan en ``raw`` y no agregan campos nuevos.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

COLUMNAS = [
    "id_evento",
    "id_origen",
    "id_pick",
    "red",
    "estacion",
    "loc",
    "cha",
    "fase",
    "llegada_utc",
    "llegada_us",
    "correccion_s",
    "residual_s",
    "azimut",
    "distancia",
    "usada",
    "peso",
    "polaridad",
    "modo_pick",
    "pick_autor",
    "pick_agencia",
    "pick_metodo",
    "snr",
    "mag_estacion",
    "tipo_mag_estacion",
    "tiene_magnitud",
    "mag_est_residuo",
    "qc_estacion",
    "est_lat",
    "est_lon",
    "est_elev",
    "est_lugar",
    "est_pais",
    "base_datos",
]

COLUMNAS_EXTRA = [
    "est_lista",
    "est_vigencia",
    "software",
    "origen_local",
]

CABECERA = COLUMNAS + COLUMNAS_EXTRA


def normalizar_fase(valor) -> str:
    """Reduce la fase de Seisan a P/S cuando corresponde.

    ``IP`` y ``EP`` son P; ``ES`` es S. Las amplitudes (``IAML``) y cualquier
    otra fase que no empiece con P o S se descartan para la propagación, pero
    no se escriben como arribo.
    """
    token = str(valor or "").strip().upper()
    if not token:
        return ""
    token = token.split()[0]
    if token[0] in ("I", "E") and len(token) > 1 and token[1] in ("P", "S"):
        token = token[1:]
    if token and token[0] in ("P", "S"):
        return token
    return ""


def formatear_pick(valor: datetime | None) -> tuple[str, str]:
    """Devuelve la llegada en UTC (segundos) y los microsegundos por separado."""
    if valor is None:
        return "", ""
    if valor.tzinfo is not None:
        valor = valor.astimezone(UTC).replace(tzinfo=None)
    return valor.strftime("%Y-%m-%d %H:%M:%S"), f"{valor.microsecond:06d}"


def parsear_canal(valor) -> tuple[str, str, str, str]:
    """Separa un canal NSLCO en red, estación, localización y canal."""
    partes = str(valor or "").strip().split(".")
    if len(partes) >= 4:
        return partes[0], partes[1], partes[2], partes[3]
    if len(partes) == 3:
        return partes[0], partes[1], partes[2], ""
    if len(partes) == 2:
        return partes[0], partes[1], "", ""
    if len(partes) == 1 and partes[0]:
        return "", partes[0], "", ""
    return "", "", "", ""


def escribir(ruta: Path, filas: list[dict]) -> Path:
    """Escribe las filas de arribos con la cabecera canónica."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.DictWriter(
            archivo, fieldnames=CABECERA, extrasaction="ignore"
        )
        escritor.writeheader()
        for fila in filas:
            escritor.writerow({clave: fila.get(clave, "") for clave in CABECERA})
    return ruta
