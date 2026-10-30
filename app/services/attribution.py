"""Atribución de analistas a eventos publicados.

Espejo de la lógica de ``generajson._analistas_para_evento`` del proyecto base:
cruza un evento del catálogo público con las soluciones locales de Seisan y
SeisComp para deducir qué analista lo trabajó. Se usa para enriquecer los
informes de repetidos publicados.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

RADIO_TIERRA_KM = 6371.0088


def _a_numero(texto):
    if texto is None:
        return None
    limpio = str(texto).strip()
    if not limpio:
        return None
    try:
        return float(limpio)
    except ValueError:
        return None


def _clave_fecha(texto) -> str:
    """Normaliza espacios: eventquery y los informes no siempre coinciden."""
    return " ".join(str(texto or "").split())


def distancia_km(lat1, lon1, lat2, lon2):
    valores = [_a_numero(lat1), _a_numero(lon1), _a_numero(lat2), _a_numero(lon2)]
    if any(valor is None for valor in valores):
        return None
    la1, lo1, la2, lo2 = valores
    phi1, phi2 = math.radians(la1), math.radians(la2)
    dphi = math.radians(la2 - la1)
    dlambda = math.radians(lo2 - lo1)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * RADIO_TIERRA_KM * math.asin(min(1.0, math.sqrt(h)))


def cargar_atribucion(workspace: Path, fuente: str) -> dict[str, list[dict]] | None:
    """Índice {fecha_eventquery: [filas de atribución]} o None si no existe."""
    ruta = workspace / "datos" / f"atribucion_{fuente}.csv"
    if not ruta.is_file():
        return None
    indice: dict[str, list[dict]] = {}
    try:
        with ruta.open(encoding="utf-8-sig", newline="") as archivo:
            for fila in csv.DictReader(archivo):
                indice.setdefault(_clave_fecha(fila.get("fecha_eventquery")), []).append(fila)
    except OSError:
        return None
    return indice or None


def analistas_para_evento(
    indice: dict[str, list[dict]] | None,
    fecha_hora,
    latitud,
    longitud,
) -> list[dict] | None:
    """Fuentes y analistas que aportaron una solución para ese evento."""
    if not indice:
        return None

    candidatas = indice.get(_clave_fecha(fecha_hora))
    if not candidatas:
        return None

    # Si hay más de una entrada en el mismo segundo, descartar las de otro
    # evento usando una tolerancia de 0.5 km.
    if len(candidatas) > 1:
        cercanas = []
        for candidata in candidatas:
            distancia = distancia_km(
                latitud,
                longitud,
                candidata.get("lat_eventquery"),
                candidata.get("lon_eventquery"),
            )
            if distancia is not None and distancia < 0.5:
                cercanas.append(candidata)
        if cercanas:
            candidatas = cercanas

    if not candidatas:
        return None

    por_fuente: dict[str, dict] = {}
    for candidata in candidatas:
        fuente = candidata.get("fuente") or "local"
        entrada = por_fuente.setdefault(
            fuente,
            {
                "fuente": fuente,
                "n_soluciones": 0,
                "dt_seg": None,
                "km": None,
            },
        )
        entrada["n_soluciones"] += 1
        dt = _a_numero(candidata.get("dt_seg"))
        if dt is not None and (entrada["dt_seg"] is None or dt < entrada["dt_seg"]):
            distancia = distancia_km(
                latitud,
                longitud,
                candidata.get("lat_eventquery"),
                candidata.get("lon_eventquery"),
            )
            entrada["dt_seg"] = dt
            entrada["km"] = None if distancia is None else round(distancia, 1)

    for entrada in por_fuente.values():
        entrada["analistas"] = sorted(
            {
                (candidata.get("analista") or "(sin nombre)")
                for candidata in candidatas
                if (candidata.get("fuente") or "local") == entrada["fuente"]
            }
        )

    return sorted(
        por_fuente.values(),
        key=lambda entrada: 0 if entrada["fuente"] == "seiscomp" else 1,
    )


ETIQUETAS_FUENTE = {
    "seiscomp": "SeisComp",
    "seisan": "Seisan",
}


def indices_atribucion(workspace: Path) -> dict[str, dict[str, list[dict]]]:
    """Índices de atribución de SeisComp y Seisan, para cargarlos una vez."""
    return {
        fuente: cargar_atribucion(workspace, fuente)
        for fuente in ("seiscomp", "seisan")
    }


def texto_analista_probable(
    indices: dict[str, dict[str, list[dict]] | None],
    fecha_hora,
    latitud,
    longitud,
) -> str:
    """``SeisComp: nombre; Seisan: nombre`` para un evento publicado."""
    partes = []
    for fuente in ("seiscomp", "seisan"):
        indice = indices.get(fuente)
        if not indice:
            continue
        encontrados = analistas_para_evento(indice, fecha_hora, latitud, longitud)
        for entrada in encontrados or ():
            nombres = ", ".join(entrada.get("analistas") or [])
            if nombres:
                partes.append(f"{ETIQUETAS_FUENTE[fuente]}: {nombres}")
    return "; ".join(partes)


def enriquecer_eventquery(
    workspace: Path,
    columnas: list[str],
    filas: list[dict],
) -> tuple[list[str], list[dict]]:
    """Agrega la columna «Analista probable» al catálogo de Eventquery."""
    indices = indices_atribucion(workspace)
    if "Analista probable" not in columnas:
        columnas = list(columnas) + ["Analista probable"]
    for fila in filas:
        fila["Analista probable"] = texto_analista_probable(
            indices,
            fila.get("Fecha_Hora") or fila.get("fecha_hora"),
            fila.get("Latitud") or fila.get("latitud"),
            fila.get("Longitud") or fila.get("longitud"),
        )
    return columnas, filas
