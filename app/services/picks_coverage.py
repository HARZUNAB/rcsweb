"""Estaciones cercanas con registro disponible que no aportaron a la solución.

La primera pasada es barata: usa el catálogo canónico, los arribos y el
inventario de estaciones sin arribos. No lee formas de onda. Su salida es un
reporte de revisión por evento y fuente.

La confirmación de señal se hace después, bajo demanda, con el servicio de
correlación. Este módulo deja el reporte preparado para esa segunda etapa.
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from flask import current_app

from app.domain.catalogs import canonical
from app.domain.catalogs.stations import distancia_km

LOG = logging.getLogger(__name__)

RADIO_DEFECTO = 250.0
CERCA_DEFECTO = 100.0
MAX_CANDIDATAS_DEFECTO = 60

CAMPOS = (
    "fuente",
    "evento",
    "id_evento_fuente",
    "fecha_hora",
    "latitud",
    "longitud",
    "profundidad_km",
    "magnitud",
    "analista",
    "fila_catalogo",
    "n_usadas",
    "sin_picar_n",
    "no_usadas_n",
    "total_n",
    "min_distancia_km",
    "prioridad",
    "estaciones",
    "detalle",
    "senal_n",
    "senal_estaciones",
    "senal_estado",
    "senal_actualizado",
    "actualizado",
)


def ruta(workspace: Path, fuente: str) -> Path:
    return (
        Path(workspace)
        / "resultados"
        / f"revision_picks_{fuente}.csv"
    )


def _config(nombre: str, defecto):
    try:
        return current_app.config.get(nombre, defecto)
    except RuntimeError:
        return defecto


def _numero_config(nombre: str, defecto: float) -> float:
    try:
        return float(_config(nombre, defecto))
    except (TypeError, ValueError):
        return defecto


def radio_km(valor: float | None = None) -> float:
    if valor is not None:
        return float(valor)
    return _numero_config("RCS_PICKS_RADIO_KM", RADIO_DEFECTO)


def cerca_km(valor: float | None = None) -> float:
    if valor is not None:
        return float(valor)
    return _numero_config("RCS_PICKS_CERCA_KM", CERCA_DEFECTO)


def max_candidatas(valor: int | None = None) -> int:
    if valor is not None:
        return max(1, int(valor))
    return max(
        1,
        int(_numero_config("RCS_PICKS_MAX_CANDIDATAS", MAX_CANDIDATAS_DEFECTO)),
    )


def _texto(valor) -> str:
    return "" if valor is None else str(valor).strip()


def _numero(valor) -> float | None:
    try:
        return float(str(valor).strip())
    except (TypeError, ValueError):
        return None


def _es_vertical(stream: str) -> bool:
    return bool(stream) and stream.split(".")[-1].endswith("Z")


def _streams_verticales(fila: dict) -> list[str]:
    valor = fila.get("stream_ids") or fila.get("streams") or ""
    return [
        stream.strip()
        for stream in str(valor).split(";")
        if _es_vertical(stream.strip())
    ]


def _clave_estacion(fila: dict) -> tuple[str, str]:
    return (
        _texto(fila.get("network")),
        _texto(fila.get("station")),
    )


def _agrupar(registros) -> dict[str, list[dict]]:
    if isinstance(registros, dict):
        return registros
    agrupados: dict[str, list[dict]] = {}
    for registro in registros or []:
        event_id = _texto(registro.get("event_id"))
        if event_id:
            agrupados.setdefault(event_id, []).append(registro)
    return agrupados


def _distancia_a_evento(evento: dict, fila: dict) -> float | None:
    lat_evento = _numero(evento.get("latitude"))
    lon_evento = _numero(evento.get("longitude"))
    lat = _numero(fila.get("station_latitude"))
    lon = _numero(fila.get("station_longitude"))
    if None in (lat_evento, lon_evento, lat, lon):
        return None
    return distancia_km(lat_evento, lon_evento, lat, lon)


def _etiqueta_estacion(fila: dict) -> str:
    red = _texto(fila.get("network"))
    estacion = _texto(fila.get("station"))
    return f"{red}.{estacion}" if red else estacion


def _prioridad(sin_picar: int, no_usadas: int, minima: float | None, cerca: float) -> str:
    if sin_picar >= 3 or (
        sin_picar >= 1 and minima is not None and minima <= cerca
    ):
        return "Alta"
    if sin_picar >= 1 or no_usadas >= 1:
        return "Media"
    return "Informativa"


def _fila_detalle(
    *,
    tipo: str,
    fila: dict,
    distancia: float | None,
    fase: str = "",
    fases: list[str] | None = None,
) -> dict:
    return {
        "tipo": tipo,
        "network": _texto(fila.get("network")),
        "station": _texto(fila.get("station")),
        "location": _texto(fila.get("location")),
        "channel": _texto(fila.get("channel")),
        "distance_km": None if distancia is None else round(distancia, 1),
        "fase": fase,
        "fases": sorted(set(fases or [])),
        "streams": _streams_verticales(fila),
        "evidence": _texto(fila.get("evidence")),
        "waveform_status": _texto(fila.get("waveform_status")),
        "availability_source": _texto(fila.get("availability_source")),
    }


def _resumen_estaciones(detalle: list[dict], limite: int = 20) -> str:
    partes = []
    for item in detalle[:limite]:
        etiqueta = (
            f"{item['network']}.{item['station']}"
            if item.get("network")
            else item.get("station", "")
        )
        distancia = item.get("distance_km")
        sufijo = f" {distancia:.1f} km" if distancia is not None else ""
        tipo = (
            "sin picar"
            if item.get("tipo") == "sin_picar"
            else "no usada"
        )
        fases = item.get("fases") or []
        if fases:
            tipo += f" ({','.join(fases)})"
        partes.append(f"{etiqueta}{sufijo} {tipo}")
    if len(detalle) > limite:
        partes.append(f"+{len(detalle) - limite} más")
    return "; ".join(partes)


def _evento_fila(
    fuente: str,
    evento: dict,
    sin_picar: list[dict],
    no_usadas: list[dict],
    n_usadas: int,
    cerca: float,
) -> dict:
    detalle = sin_picar + no_usadas
    distancias = [
        item["distance_km"]
        for item in detalle
        if item.get("distance_km") is not None
    ]
    minima = min(distancias) if distancias else None
    prioridad = _prioridad(len(sin_picar), len(no_usadas), minima, cerca)
    return {
        "fuente": fuente,
        "evento": _texto(evento.get("event_id")),
        "id_evento_fuente": _texto(evento.get("source_event_id")),
        "fecha_hora": _texto(evento.get("event_time")),
        "latitud": evento.get("latitude", ""),
        "longitud": evento.get("longitude", ""),
        "profundidad_km": _texto(evento.get("depth_km")),
        "magnitud": _texto(evento.get("magnitude")),
        "analista": _texto(evento.get("analyst")),
        "fila_catalogo": evento.get("raw_index", ""),
        "n_usadas": n_usadas,
        "sin_picar_n": len(sin_picar),
        "no_usadas_n": len(no_usadas),
        "total_n": len(detalle),
        "min_distancia_km": None if minima is None else round(minima, 1),
        "prioridad": prioridad,
        "estaciones": _resumen_estaciones(detalle),
        "detalle": json.dumps(detalle, ensure_ascii=False),
        "senal_n": 0,
        "senal_estaciones": "",
        "senal_estado": "pendiente",
        "senal_actualizado": "",
        "actualizado": datetime.now(UTC).isoformat(),
    }


def generar(
    workspace: Path,
    fuente: str,
    *,
    eventos: list[dict] | None = None,
    arribos=None,
    sin_arribos=None,
    radio: float | None = None,
    cerca: float | None = None,
    maximo: int | None = None,
) -> dict:
    """Genera el reporte de estaciones cercanas sin aportar.

    ``arribos`` y ``sin_arribos`` pueden venir ya agrupados por evento, como
    los tiene ``generar_indicios``, o como listas canónicas.
    """
    workspace = Path(workspace)
    radio_km_valor = radio_km(radio)
    cerca_valor = cerca_km(cerca)
    maximo_valor = max_candidatas(maximo)
    eventos = (
        list(eventos)
        if eventos is not None
        else canonical.leer_canonico(workspace, fuente)
    )
    arribos_por_evento = _agrupar(
        arribos
        if arribos is not None
        else canonical.leer_arribos(workspace, fuente)
    )
    sin_arribos_por_evento = _agrupar(
        sin_arribos
        if sin_arribos is not None
        else canonical.leer_estaciones_sin_arribos(workspace, fuente)
    )

    filas: list[dict] = []
    for evento in eventos:
        event_id = _texto(evento.get("event_id"))
        if not event_id:
            continue
        de_evento = arribos_por_evento.get(event_id, [])
        usadas: set[tuple[str, str]] = set()
        no_usadas_por_estacion: dict[tuple[str, str], dict] = {}
        for arribo in de_evento:
            clave = _clave_estacion(arribo)
            if arribo.get("is_used_in_solution") is True:
                usadas.add(clave)
                continue
            datos = no_usadas_por_estacion.setdefault(
                clave,
                {
                    "fila": arribo,
                    "fases": [],
                    "distancia": _distancia_a_evento(evento, arribo),
                },
            )
            fase = _texto(arribo.get("phase"))
            if fase:
                datos["fases"].append(fase)

        sin_picar: list[dict] = []
        for fila in sin_arribos_por_evento.get(event_id, []):
            clave = _clave_estacion(fila)
            if clave in usadas or clave in no_usadas_por_estacion:
                continue
            if _texto(fila.get("evidence")).upper() == "SIN_EVIDENCIA":
                continue
            if _texto(fila.get("waveform_status")).upper() == "SIN_DATOS":
                continue
            streams = _streams_verticales(fila)
            if not streams:
                continue
            distancia = _distancia_a_evento(evento, fila)
            if distancia is None or distancia > radio_km_valor:
                continue
            sin_picar.append(
                _fila_detalle(
                    tipo="sin_picar",
                    fila=fila,
                    distancia=distancia,
                )
            )

        sin_picar.sort(key=lambda item: item.get("distance_km") or 0)

        no_usadas: list[dict] = []
        for clave, datos in no_usadas_por_estacion.items():
            fila = datos["fila"]
            distancia = datos["distancia"]
            if distancia is None or distancia > radio_km_valor:
                continue
            item = _fila_detalle(
                tipo="no_usada",
                fila=fila,
                distancia=distancia,
                fases=datos["fases"],
            )
            no_usadas.append(item)
        no_usadas.sort(key=lambda item: item.get("distance_km") or 0)

        todos = sorted(
            sin_picar + no_usadas,
            key=lambda item: item.get("distance_km") or 0,
        )[:maximo_valor]
        sin_picar = [
            item for item in todos if item["tipo"] == "sin_picar"
        ]
        no_usadas = [
            item for item in todos if item["tipo"] == "no_usada"
        ]

        if not sin_picar and not no_usadas:
            continue
        calidad = evento.get("origin_quality") or {}
        n_usadas = calidad.get("used_station_count")
        if n_usadas is None:
            n_usadas = len(usadas)
        filas.append(
            _evento_fila(
                fuente,
                evento,
                sin_picar,
                no_usadas,
                int(n_usadas or 0),
                cerca_valor,
            )
        )

    filas.sort(
        key=lambda fila: (
            -{"Alta": 3, "Media": 2, "Informativa": 1}.get(
                fila.get("prioridad", ""), 0
            ),
            -int(fila.get("total_n") or 0),
            fila.get("fecha_hora") or "",
        )
    )
    destino = ruta(workspace, fuente)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name(destino.name + ".tmp")
    try:
        with temporal.open("w", encoding="utf-8", newline="") as archivo:
            escritor = csv.DictWriter(
                archivo, fieldnames=CAMPOS, extrasaction="ignore"
            )
            escritor.writeheader()
            for fila in filas:
                escritor.writerow(fila)
        temporal.replace(destino)
    finally:
        temporal.unlink(missing_ok=True)

    return {
        "eventos": len(filas),
        "sin_picar": sum(int(fila["sin_picar_n"]) for fila in filas),
        "no_usadas": sum(int(fila["no_usadas_n"]) for fila in filas),
        "radio_km": radio_km_valor,
        "cerca_km": cerca_valor,
    }


def actualizar_senal(
    workspace: Path,
    fuente: str,
    event_id: str,
    *,
    senal_n: int,
    senal_estaciones: str,
    senal_estado: str,
    actualizado: str | None = None,
) -> bool:
    """Actualiza el estado de señal de un evento en el reporte."""
    destino = ruta(workspace, fuente)
    if not destino.is_file():
        return False
    with destino.open(encoding="utf-8", newline="") as archivo:
        filas = list(csv.DictReader(archivo))
    encontrado = False
    for fila in filas:
        if _texto(fila.get("evento")) != event_id:
            continue
        fila["senal_n"] = str(int(senal_n))
        fila["senal_estaciones"] = senal_estaciones
        fila["senal_estado"] = senal_estado
        fila["senal_actualizado"] = (
            actualizado or datetime.now(UTC).isoformat()
        )
        encontrado = True
    if not encontrado:
        return False
    temporal = destino.with_name(destino.name + ".tmp")
    try:
        with temporal.open("w", encoding="utf-8", newline="") as archivo:
            escritor = csv.DictWriter(
                archivo, fieldnames=CAMPOS, extrasaction="ignore"
            )
            escritor.writeheader()
            escritor.writerows(filas)
        temporal.replace(destino)
    finally:
        temporal.unlink(missing_ok=True)
    return True


def leer(workspace: Path, fuente: str) -> list[dict]:
    destino = ruta(workspace, fuente)
    if not destino.is_file():
        return []
    try:
        with destino.open(encoding="utf-8", newline="") as archivo:
            filas = list(csv.DictReader(archivo))
    except (OSError, csv.Error):
        LOG.warning("No se pudo leer %s", destino, exc_info=True)
        return []
    for fila in filas:
        detalle = fila.get("detalle")
        if detalle:
            try:
                fila["detalle"] = json.loads(detalle)
            except ValueError:
                fila["detalle"] = []
        else:
            fila["detalle"] = []
    return filas


def resumen(workspace: Path, fuente: str) -> dict:
    filas = leer(workspace, fuente)
    return {
        "eventos": len(filas),
        "sin_picar": sum(int(fila.get("sin_picar_n") or 0) for fila in filas),
        "no_usadas": sum(int(fila.get("no_usadas_n") or 0) for fila in filas),
        "senal": sum(int(fila.get("senal_n") or 0) for fila in filas),
    }


__all__ = [
    "CAMPOS",
    "actualizar_senal",
    "cerca_km",
    "generar",
    "leer",
    "max_candidatas",
    "radio_km",
    "resumen",
    "ruta",
]
