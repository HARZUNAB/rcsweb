"""Validadores de catálogos.

Validan formato, cantidad de eventos y cobertura temporal antes de encolar un
trabajo. No reemplazan al pipeline: detectan los errores que lo harían fallar.
"""

from __future__ import annotations

import csv
import datetime
import re
from pathlib import Path

RE_EVENTO_SEISAN = re.compile(
    r"^\s*(\d{4})\s+(\d{1,2})\s+(\d{1,2})\s+"
    r"(\d{1,4})\s+(\d{1,2}(?:\.\d+)?)"
)

COLUMNAS_EVENTQUERY = ("time", "lat", "lon", "depth", "mag", "tipo_mag", "ref", "perc")
ALIASES_EVENTQUERY = {
    "time": ("time",),
    "lat": ("lat", "latitude"),
    "lon": ("lon", "longitude"),
    "depth": ("depth", "depth [km]"),
    "mag": ("mag", "magnitude"),
    "tipo_mag": ("tipo_mag", "magnitude_type"),
    "ref": ("ref", "region_name"),
    "perc": ("perc", "felt"),
}
COLUMNAS_SEISCOMP = (
    "ot_utc",
    "latitud",
    "longitud",
    "profundidad_km",
    "magnitud",
    "tipo_magnitud",
    "operador",
)


def _resultado(codigo: str) -> dict:
    return {
        "codigo": codigo,
        "ok": False,
        "errores": [],
        "advertencias": [],
        "eventos": 0,
        "desde": None,
        "hasta": None,
    }


def _instante(texto):
    if texto is None:
        return None
    limpio = str(texto).strip()
    if not limpio:
        return None
    limpio = limpio.replace("Z", "+00:00")
    instante = None
    try:
        instante = datetime.datetime.fromisoformat(limpio)
    except ValueError:
        pass
    if instante is None:
        for formato in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                instante = datetime.datetime.strptime(limpio[:26], formato)
                break
            except ValueError:
                continue
    if instante is None:
        return None
    if instante.tzinfo is not None:
        instante = instante.astimezone(datetime.UTC).replace(tzinfo=None)
    return instante


def _numero(texto):
    try:
        return float(str(texto).strip())
    except (TypeError, ValueError):
        return None


def _normalizar_limite(valor):
    if valor is None:
        return None
    if isinstance(valor, datetime.datetime):
        if valor.tzinfo is not None:
            return valor.astimezone(datetime.UTC).replace(tzinfo=None)
        return valor
    if isinstance(valor, datetime.date):
        return datetime.datetime.combine(valor, datetime.time.min)
    return _instante(valor)


def _cobertura(resultado: dict, periodo_inicio=None, periodo_fin=None) -> None:
    instantes = [i for i in (resultado["desde"], resultado["hasta"]) if i is not None]
    if not instantes:
        return
    resultado["desde"] = min(instantes).isoformat()
    resultado["hasta"] = max(instantes).isoformat()

    inicio = _normalizar_limite(periodo_inicio)
    fin = _normalizar_limite(periodo_fin)
    if inicio is not None and min(instantes) > inicio:
        resultado["advertencias"].append(
            "El catálogo empieza después del inicio del período solicitado."
        )
    if fin is not None and max(instantes) < fin:
        resultado["advertencias"].append(
            "El catálogo termina antes del fin del período solicitado."
        )


def _leer_csv(ruta: Path):
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        lector = csv.DictReader(archivo)
        return [c.strip().lstrip("\ufeff") for c in (lector.fieldnames or [])], list(lector)


def _campo_eventquery(fila: dict, nombre: str):
    for alias in ALIASES_EVENTQUERY[nombre]:
        if alias in fila:
            return fila[alias]
    return None


def validar_eventquery(ruta: Path, periodo_inicio=None, periodo_fin=None) -> dict:
    resultado = _resultado("eventquery")
    if not ruta.is_file():
        resultado["errores"].append("No se encontró el archivo.")
        return resultado
    if ruta.stat().st_size == 0:
        resultado["errores"].append("El archivo está vacío.")
        return resultado

    try:
        columnas, filas = _leer_csv(ruta)
    except (OSError, UnicodeError, csv.Error) as exc:
        resultado["errores"].append(f"No se pudo leer el CSV: {exc}")
        return resultado

    faltantes = [
        canonica
        for canonica in COLUMNAS_EVENTQUERY
        if not any(alias in columnas for alias in ALIASES_EVENTQUERY[canonica])
    ]
    if faltantes:
        resultado["errores"].append("Faltan columnas: " + ", ".join(faltantes))
        return resultado

    instantes = []
    for fila in filas:
        instante = _instante(_campo_eventquery(fila, "time"))
        lat = _numero(_campo_eventquery(fila, "lat"))
        lon = _numero(_campo_eventquery(fila, "lon"))
        if instante is None or lat is None or lon is None:
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        instantes.append(instante)
        resultado["eventos"] += 1

    if resultado["eventos"] == 0:
        resultado["errores"].append("No hay eventos válidos (fecha y coordenadas).")
        return resultado

    resultado["desde"] = min(instantes)
    resultado["hasta"] = max(instantes)
    _cobertura(resultado, periodo_inicio, periodo_fin)
    resultado["ok"] = True
    return resultado


def validar_seisan(ruta: Path, periodo_inicio=None, periodo_fin=None) -> dict:
    resultado = _resultado("seisan")
    if not ruta.is_file():
        resultado["errores"].append("No se encontró select.out.")
        return resultado
    if ruta.stat().st_size == 0:
        resultado["errores"].append("El archivo está vacío.")
        return resultado

    instantes = []
    try:
        with ruta.open(encoding="latin-1", errors="replace") as archivo:
            for linea in archivo:
                coincidencia = RE_EVENTO_SEISAN.match(linea)
                if not coincidencia:
                    continue
                anio, mes, dia, hhmm, segundo = coincidencia.groups()
                try:
                    hora = int(hhmm) // 100
                    minuto = int(hhmm) % 100
                    instante = datetime.datetime(
                        int(anio),
                        int(mes),
                        int(dia),
                        hora,
                        minuto,
                        int(float(segundo)),
                    )
                except ValueError:
                    continue
                instantes.append(instante)
    except OSError as exc:
        resultado["errores"].append(f"No se pudo leer select.out: {exc}")
        return resultado

    resultado["eventos"] = len(instantes)
    if not instantes:
        resultado["errores"].append(
            "No se encontraron eventos de Seisan (líneas con año, mes, día y hora)."
        )
        return resultado

    resultado["desde"] = min(instantes)
    resultado["hasta"] = max(instantes)
    _cobertura(resultado, periodo_inicio, periodo_fin)
    resultado["ok"] = True
    return resultado


def validar_seiscomp(ruta: Path, periodo_inicio=None, periodo_fin=None) -> dict:
    resultado = _resultado("seiscomp")
    if not ruta.is_file():
        resultado["errores"].append("No se encontró la exportación de SeisComp.")
        return resultado
    if ruta.stat().st_size == 0:
        resultado["errores"].append("El archivo está vacío.")
        return resultado

    try:
        columnas, filas = _leer_csv(ruta)
    except (OSError, UnicodeError, csv.Error) as exc:
        resultado["errores"].append(f"No se pudo leer el CSV: {exc}")
        return resultado

    faltantes = [c for c in COLUMNAS_SEISCOMP if c not in columnas]
    if faltantes:
        resultado["errores"].append("Faltan columnas: " + ", ".join(faltantes))
        return resultado

    instantes = []
    for fila in filas:
        instante = _instante(fila.get("ot_utc"))
        lat = _numero(fila.get("latitud"))
        lon = _numero(fila.get("longitud"))
        if instante is None or lat is None or lon is None:
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        instantes.append(instante)
        resultado["eventos"] += 1

    if resultado["eventos"] == 0:
        resultado["errores"].append("No hay eventos válidos (fecha y coordenadas).")
        return resultado

    resultado["desde"] = min(instantes)
    resultado["hasta"] = max(instantes)
    _cobertura(resultado, periodo_inicio, periodo_fin)
    resultado["ok"] = True
    return resultado


def validar_fuente(codigo: str, ruta: Path, periodo_inicio=None, periodo_fin=None) -> dict:
    from .sources import fuente

    formato = fuente(codigo).codigo
    validadores = {
        "eventquery": validar_eventquery,
        "seisan": validar_seisan,
        "seiscomp": validar_seiscomp,
    }
    validador = validadores.get(formato)
    if validador is None:
        resultado = _resultado(codigo)
        resultado["errores"].append(f"No hay validador para el formato '{formato}'.")
        return resultado
    return validador(ruta, periodo_inicio, periodo_fin)
