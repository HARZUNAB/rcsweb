"""Confirmación de señal para estaciones cercanas sin aportar.

Esta es la segunda etapa del indicador: lee las formas de onda de las
candidatas y aplica la regla de bandas. El resultado actualiza el reporte de
cobertura de picks y reemplaza ``señal pendiente`` por el conteo confirmado.

La correlación se delega al servicio auxiliar ``disponibilidad``; este módulo
no lee el SDS directamente.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
from flask import has_app_context
from sqlalchemy import select

from app.domain.catalogs import canonical
from app.domain.catalogs.stations import distancia_km
from app.services import availability, picks_coverage

LOG = logging.getLogger(__name__)

BANDAS = ((1.0, 5.0), (1.0, 10.0), (2.0, 15.0))
MIN_BANDAS = 2
STA_LTA_MIN = 3.0
RACHA_MIN = 0.7
MAX_EVENTOS = 50
MAX_CANDIDATAS = 20
ESTADOS_SENAL = {"podria_picarse", "senal_detectada"}
ESTADOS_TERMINALES = {"analizado", "sin_datos", "sin_candidatas"}


class SignalBackupError(RuntimeError):
    """No se pudo respaldar el análisis de señal antes de borrar un trabajo."""

PARAMETROS = {
    "fs": 100.0,
    "template_before_s": 1.0,
    "template_after_s": 7.0,
    "candidate_before_s": 10.0,
    "candidate_after_s": 30.0,
    "max_lag_s": 5.0,
    "sta_s": 0.5,
    "lta_s": 10.0,
    "sta_lta_before_s": 1.5,
    "sta_lta_after_s": 4.0,
    "sta_lta_persistencia_s": RACHA_MIN,
    "cc_min": 0.5,
    "sta_lta_min": STA_LTA_MIN,
}


def _texto(valor) -> str:
    return "" if valor is None else str(valor).strip()


def _numero(valor) -> float | None:
    try:
        return float(str(valor).strip())
    except (TypeError, ValueError):
        return None


def _instante(valor) -> datetime | None:
    limpio = " ".join(str(valor or "").strip().replace("Z", "+00:00").split())
    if not limpio:
        return None
    try:
        instante = datetime.fromisoformat(limpio)
    except ValueError:
        return None
    if instante.tzinfo is not None:
        instante = instante.astimezone(UTC).replace(tzinfo=None)
    return instante


def _normalizar(valor) -> str:
    numero = _numero(valor)
    if numero is not None:
        return f"{numero:.6f}"
    return _texto(valor)


def _normalizar_fecha(valor) -> str:
    instante = _instante(valor)
    if instante is not None:
        return instante.isoformat()
    return _texto(valor)


def huella_regla() -> str:
    """Huella de la regla; cambiarla invalida todos los resultados."""
    payload = {
        "bandas": BANDAS,
        "min_bandas": MIN_BANDAS,
        **PARAMETROS,
    }
    crudo = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(crudo.encode("utf-8")).hexdigest()[:16]


def huella_fila(fila: dict) -> str:
    """Huella del evento y sus candidatas para reutilizar el resultado."""
    candidatas = []
    for item in fila.get("detalle") or []:
        if not isinstance(item, dict):
            continue
        candidatas.append(
            {
                "tipo": _texto(item.get("tipo")),
                "network": _texto(item.get("network")),
                "station": _texto(item.get("station")),
                "location": _texto(item.get("location")),
                "channel": _texto(item.get("channel")),
                "distance_km": _normalizar(item.get("distance_km")),
                "streams": sorted(
                    _texto(stream)
                    for stream in item.get("streams") or []
                ),
            }
        )
    candidatas.sort(
        key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False)
    )
    payload = {
        "evento": _texto(fila.get("evento")),
        "fecha_hora": _normalizar_fecha(fila.get("fecha_hora")),
        "latitud": _normalizar(fila.get("latitud")),
        "longitud": _normalizar(fila.get("longitud")),
        "profundidad_km": _normalizar(fila.get("profundidad_km")),
        "magnitud": _normalizar(fila.get("magnitud")),
        "candidatas": candidatas,
        "regla": huella_regla(),
    }
    crudo = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(crudo.encode("utf-8")).hexdigest()


def _modelo():
    from app.models import PicksSignalResult

    return PicksSignalResult


def _sesion():
    from app.extensions import db

    return db.session


def guardar_resultado(
    fuente: str,
    fila: dict,
    resultado: dict,
    *,
    analizado_en: datetime | None = None,
) -> bool:
    """Guarda el resultado vigente en la base, fuera del CSV de cobertura."""
    event_id = _texto(fila.get("evento"))
    if not event_id or not has_app_context():
        return False
    try:
        modelo = _modelo()
        sesion = _sesion()
        from app.models import utcnow

        fingerprint = huella_fila(fila)
        regla = huella_regla()
        existente = sesion.scalar(
            select(modelo).where(
                modelo.source_id == fuente,
                modelo.event_id == event_id,
                modelo.fingerprint == fingerprint,
                modelo.rule_version == regla,
            )
        )
        if existente is None:
            existente = modelo(
                source_id=fuente,
                event_id=event_id,
                fingerprint=fingerprint,
                rule_version=regla,
            )
            sesion.add(existente)
        existente.estado = _texto(resultado.get("senal_estado")) or "pendiente"
        existente.senal_n = int(resultado.get("senal_n") or 0)
        existente.senal_estaciones = _texto(
            resultado.get("senal_estaciones")
        )
        existente.detalle = resultado.get("detalle") or None
        existente.error = _texto(resultado.get("error"))
        existente.analizado_en = analizado_en or utcnow()
        sesion.commit()
        return True
    except Exception:  # noqa: BLE001 - la caché no debe romper el análisis
        LOG.exception("No se pudo guardar el resultado de señal")
        try:
            _sesion().rollback()
        except Exception:  # noqa: BLE001
            pass
        return False


def mapa_resultados(
    fuente: str,
    filas: list[dict],
) -> dict[tuple[str, str], object]:
    """Resultados vigentes por (evento, huella) para todas las filas."""
    if not has_app_context():
        return {}
    claves = []
    for fila in filas:
        event_id = _texto(fila.get("evento"))
        if not event_id:
            continue
        claves.append((event_id, huella_fila(fila)))
    if not claves:
        return {}
    claves_set = set(claves)
    event_ids = sorted({event_id for event_id, _ in claves})
    regla = huella_regla()
    try:
        modelo = _modelo()
        sesion = _sesion()
        resultados = sesion.scalars(
            select(modelo).where(
                modelo.source_id == fuente,
                modelo.rule_version == regla,
                modelo.event_id.in_(event_ids),
                modelo.estado.in_(sorted(ESTADOS_TERMINALES)),
            )
        ).all()
    except Exception:  # noqa: BLE001 - sin base se usa el CSV
        LOG.exception("No se pudieron leer los resultados de señal")
        try:
            _sesion().rollback()
        except Exception:  # noqa: BLE001
            pass
        return {}
    return {
        (_texto(resultado.event_id), resultado.fingerprint): resultado
        for resultado in resultados
        if (_texto(resultado.event_id), resultado.fingerprint) in claves_set
    }


def resultado_evento(
    workspace: Path,
    fuente: str,
    event_id: str,
):
    """Resultado vigente de un evento concreto, o ``None``."""
    event_id = _texto(event_id)
    if not event_id:
        return None
    fila = picks_coverage.fila_evento(workspace, fuente, event_id)
    if fila is None:
        return None
    return mapa_resultados(fuente, [fila]).get(
        (event_id, huella_fila(fila))
    )


def campos_desde_resultado(resultado) -> dict:
    actualizado = ""
    if resultado.analizado_en is not None:
        actualizado = resultado.analizado_en.isoformat()
    return {
        "senal_n": int(resultado.senal_n or 0),
        "senal_estaciones": resultado.senal_estaciones or "",
        "senal_estado": resultado.estado or "pendiente",
        "senal_actualizado": actualizado,
    }


def importar_reporte(
    workspace: Path,
    fuente: str,
    *,
    estricto: bool = False,
) -> int:
    """Lleva a la base los resultados que solo están en el CSV.

    ``estricto`` se usa antes de borrar un trabajo: si no se puede guardar,
    se levanta ``SignalBackupError`` para no perder el resultado.
    """
    if not has_app_context():
        if estricto:
            raise SignalBackupError(
                "No hay contexto de aplicación para respaldar la señal."
            )
        return 0
    filas = picks_coverage.leer(workspace, fuente)
    if not filas:
        return 0
    mapa = mapa_resultados(fuente, filas)
    importados = 0
    for fila in filas:
        if fila.get("senal_estado") not in ESTADOS_TERMINALES:
            continue
        event_id = _texto(fila.get("evento"))
        if not event_id or (event_id, huella_fila(fila)) in mapa:
            continue
        resultado = {
            "senal_n": int(fila.get("senal_n") or 0),
            "senal_estaciones": _texto(fila.get("senal_estaciones")),
            "senal_estado": _texto(fila.get("senal_estado")),
            "detalle": {},
        }
        guardado = guardar_resultado(
            fuente,
            fila,
            resultado,
            analizado_en=_instante(fila.get("senal_actualizado")),
        )
        if not guardado and estricto:
            raise SignalBackupError(
                f"No se pudo respaldar la señal de {event_id} ({fuente})."
            )
        if guardado:
            importados += 1
    return importados


def completar_reporte(workspace: Path, fuente: str) -> int:
    """Repuebla el CSV con los resultados vigentes de la base."""
    if not has_app_context():
        return 0
    importar_reporte(workspace, fuente)
    filas = picks_coverage.leer(workspace, fuente)
    if not filas:
        return 0
    mapa = mapa_resultados(fuente, filas)
    if not mapa:
        return 0
    cambios: dict[str, dict] = {}
    for fila in filas:
        if int(fila.get("total_n") or 0) <= 0:
            continue
        event_id = _texto(fila.get("evento"))
        resultado = mapa.get((event_id, huella_fila(fila)))
        if resultado is None:
            continue
        campos = campos_desde_resultado(resultado)
        if (
            str(fila.get("senal_n") or "0") == str(campos["senal_n"])
            and _texto(fila.get("senal_estaciones"))
            == campos["senal_estaciones"]
            and _texto(fila.get("senal_estado")) == campos["senal_estado"]
        ):
            continue
        cambios[event_id] = campos
    if not cambios:
        return 0
    return picks_coverage.actualizar_senales(workspace, fuente, cambios)


def ruta_resumen(workspace: Path, fuente: str) -> Path:
    return Path(workspace) / "resultados" / f"senal_ultimo_{fuente}.json"


def guardar_resumen(workspace: Path, fuente: str, resumen: dict) -> None:
    destino = ruta_resumen(workspace, fuente)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name(destino.name + ".tmp")
    try:
        temporal.write_text(
            json.dumps(resumen, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporal.replace(destino)
    except OSError:
        LOG.exception("No se pudo guardar el resumen de señal")
    finally:
        temporal.unlink(missing_ok=True)


def leer_resumen(workspace: Path, fuente: str) -> dict:
    destino = ruta_resumen(workspace, fuente)
    if not destino.is_file():
        return {}
    try:
        datos = json.loads(destino.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return datos if isinstance(datos, dict) else {}


def _es_vertical(stream: str) -> bool:
    return bool(stream) and stream.split(".")[-1].endswith("Z")


MAX_STREAMS_ESTACION = 3


def _prioridad_canal(stream: str) -> int:
    """Prefiere canales verticales de mayor frecuencia para 1–15 Hz."""
    canal = _texto(stream).split(".")[-1].upper()
    if not canal.endswith("Z"):
        return 99
    prefijo = canal[:2]
    if prefijo in ("HH", "HN", "EH", "SH"):
        return 0
    if prefijo == "BH":
        return 1
    if prefijo in ("LH", "VH"):
        return 3
    return 2


def _streams_verticales(item: dict) -> list[str]:
    """Verticales de la estación, del más apto al menos apto."""
    stream_ids = []
    for stream in item.get("streams") or []:
        limpio = _texto(stream)
        if limpio and _es_vertical(limpio) and limpio not in stream_ids:
            stream_ids.append(limpio)
    if not stream_ids:
        network = _texto(item.get("network"))
        station = _texto(item.get("station"))
        location = _texto(item.get("location"))
        channel = _texto(item.get("channel"))
        if network and station and channel:
            stream_ids.append(
                f"{network}.{station}.{location}.{channel[:-1]}Z"
            )
    ordenados = sorted(
        enumerate(stream_ids),
        key=lambda par: (_prioridad_canal(par[1]), par[0]),
    )
    return [stream for _posicion, stream in ordenados][:MAX_STREAMS_ESTACION]


def _stream_vertical(item: dict) -> str:
    streams = _streams_verticales(item)
    return streams[0] if streams else ""


def _etiqueta(network: str, station: str) -> str:
    return f"{network}.{station}" if network else station


def _picks_evento(evento: dict, arribos: list[dict]) -> list[dict]:
    instante = _instante(evento.get("event_time"))
    lat = _numero(evento.get("latitude"))
    lon = _numero(evento.get("longitude"))
    if instante is None or lat is None or lon is None:
        return []
    picks = []
    for arribo in arribos:
        if not _texto(arribo.get("phase")).upper().startswith("P"):
            continue
        lat_estacion = _numero(arribo.get("station_latitude"))
        lon_estacion = _numero(arribo.get("station_longitude"))
        llegada = _instante(arribo.get("pick_time"))
        if lat_estacion is None or lon_estacion is None or llegada is None:
            continue
        segundos = (llegada - instante).total_seconds()
        if segundos <= 0:
            continue
        stream = "{}.{}.{}.{}".format(
            _texto(arribo.get("network")),
            _texto(arribo.get("station")),
            _texto(arribo.get("location")),
            _texto(arribo.get("channel")),
        )
        picks.append(
            {
                "distance_km": distancia_km(
                    lat, lon, lat_estacion, lon_estacion
                ),
                "segundos": segundos,
                "stream": stream,
                "station": _etiqueta(
                    _texto(arribo.get("network")),
                    _texto(arribo.get("station")),
                ),
                "pick_time": _texto(arribo.get("pick_time")),
                "usada": arribo.get("is_used_in_solution") is True,
            }
        )
    return picks


def _ajuste(evento: dict, picks: list[dict]) -> tuple[float, float]:
    """Ajuste t = a + b * distancia hipocentral."""
    profundidad = _numero(evento.get("depth_km")) or 0.0
    usados = [pick for pick in picks if pick["usada"]]
    base = usados if len(usados) >= 3 else picks
    puntos = [
        (
            math.hypot(pick["distance_km"], profundidad),
            pick["segundos"],
        )
        for pick in base
        if pick.get("distance_km") is not None
    ]
    if len(puntos) < 3:
        return 0.0, 1.0 / 6.0
    xs = np.array([punto[0] for punto in puntos])
    ys = np.array([punto[1] for punto in puntos])
    try:
        pendiente, intercepto = np.polyfit(xs, ys, 1)
    except (np.linalg.LinAlgError, ValueError):
        return 0.0, 1.0 / 6.0
    if not np.isfinite(pendiente) or not np.isfinite(intercepto):
        return 0.0, 1.0 / 6.0
    if pendiente <= 0 or intercepto < 0:
        return 0.0, 1.0 / 6.0
    return float(intercepto), float(pendiente)


def _candidatos(
    evento: dict,
    detalle: list[dict],
    intercepto: float,
    pendiente: float,
    max_candidatas: int,
) -> list[dict]:
    instante = _instante(evento.get("event_time"))
    profundidad = _numero(evento.get("depth_km")) or 0.0
    if instante is None:
        return []
    salida = []
    for item in detalle:
        streams = _streams_verticales(item)
        distancia = _numero(item.get("distance_km"))
        if not streams or distancia is None:
            continue
        hipo = math.hypot(distancia, profundidad)
        esperado = instante + timedelta(
            seconds=intercepto + pendiente * hipo
        )
        network_base = _texto(item.get("network"))
        station_base = _texto(item.get("station"))
        location_base = _texto(item.get("location"))
        for stream in streams:
            partes = stream.split(".")
            if len(partes) == 4:
                network, station, location, canal = partes
            else:
                network = network_base
                station = station_base
                location = location_base
                canal = stream.split(".")[-1]
            salida.append(
                {
                    "stream": stream,
                    "station": (
                        f"AVAIL {network}.{station}.{location}.{canal}"
                    ),
                    "distance_km": round(distancia, 1),
                    "expected_time": esperado.isoformat(),
                    "etiqueta": _etiqueta(network, station),
                    "_prioridad_canal": _prioridad_canal(stream),
                }
            )
    salida.sort(
        key=lambda item: (
            item["distance_km"],
            item["_prioridad_canal"],
            item["stream"],
        )
    )
    for candidato in salida:
        candidato.pop("_prioridad_canal", None)
    return salida[:max_candidatas]


def _payload(
    referencia: dict,
    candidatos: list[dict],
    banda: tuple[float, float],
) -> dict:
    return {
        "reference": {
            "stream": referencia["stream"],
            "pick_time": referencia["pick_time"],
            "distance_km": round(referencia["distance_km"], 1),
        },
        "candidates": [
            {
                "stream": candidato["stream"],
                "station": candidato["station"],
                "distance_km": candidato["distance_km"],
                "expected_time": candidato["expected_time"],
            }
            for candidato in candidatos
        ],
        "band": [banda[0], banda[1]],
        **PARAMETROS,
    }


def _etiqueta_banda(banda: tuple[float, float]) -> str:
    return f"{banda[0]:g}-{banda[1]:g}"


def _combinar(
    respuestas: list[tuple[tuple[float, float], dict]],
    candidatos: list[dict],
) -> dict:
    por_estacion = {
        candidato["station"]: candidato["etiqueta"]
        for candidato in candidatos
    }
    etiquetas = set(por_estacion.values())
    bandas: dict[str, set[str]] = defaultdict(set)
    con_datos = False
    for banda, respuesta in respuestas:
        for item in respuesta.get("resultados", []):
            station = _texto(item.get("station"))
            if not station.startswith("AVAIL") or station.endswith(" NEG"):
                continue
            if item.get("status") == "CON_DATOS":
                con_datos = True
            etiqueta = por_estacion.get(station)
            if etiqueta is None:
                partes = station.replace("AVAIL ", "").split(".")
                if len(partes) >= 2:
                    posible = _etiqueta(partes[0], partes[1])
                    if posible in etiquetas:
                        etiqueta = posible
            if etiqueta is None:
                continue
            if item.get("status") != "CON_DATOS":
                continue
            if item.get("clasificacion") not in ESTADOS_SENAL:
                continue
            racha = _numero(item.get("sta_lta_racha_s")) or 0.0
            if racha < RACHA_MIN:
                continue
            bandas[etiqueta].add(_etiqueta_banda(banda))
    claras = {
        etiqueta: sorted(valores)
        for etiqueta, valores in bandas.items()
        if len(valores) >= MIN_BANDAS
    }
    return {
        "senal_n": len(claras),
        "senal_estaciones": "; ".join(
            f"{etiqueta} ({','.join(valores)})"
            for etiqueta, valores in sorted(claras.items())
        ),
        "senal_estado": (
            "analizado"
            if con_datos
            else ("sin_datos" if candidatos else "sin_candidatas")
        ),
        "detalle": {
            "candidatas": len(candidatos),
            "candidatas_labels": sorted(
                {candidato["etiqueta"] for candidato in candidatos}
            ),
            "claras": {
                etiqueta: valores
                for etiqueta, valores in sorted(claras.items())
            },
        },
    }


def analizar_evento(
    evento: dict,
    detalle: list[dict],
    arribos: list[dict],
    *,
    max_candidatas: int = MAX_CANDIDATAS,
    correlacionar_fn=None,
) -> dict:
    correlacionar = correlacionar_fn or availability.correlacionar
    picks = _picks_evento(evento, arribos)
    if not picks:
        return {
            "senal_n": 0,
            "senal_estaciones": "",
            "senal_estado": "sin_datos",
            "detalle": {},
        }
    intercepto, pendiente = _ajuste(evento, picks)
    candidatos = _candidatos(
        evento, detalle, intercepto, pendiente, max_candidatas
    )
    if not candidatos:
        return {
            "senal_n": 0,
            "senal_estaciones": "",
            "senal_estado": "sin_candidatas",
            "detalle": {},
        }
    referencias = sorted(
        (
            pick
            for pick in picks
            if _es_vertical(pick.get("stream") or "")
            and pick.get("pick_time")
            and pick.get("distance_km") is not None
        ),
        key=lambda item: item["distance_km"],
    )
    referencias_usadas = referencias[:3]
    referencias_fallidas = 0
    for referencia in referencias_usadas:
        excluidos = {
            referencia["stream"],
        }
        disponibles = [
            candidato
            for candidato in candidatos
            if candidato["stream"] not in excluidos
        ]
        if not disponibles:
            continue
        respuestas = []
        fallos = 0
        for banda in BANDAS:
            payload = _payload(referencia, disponibles, banda)
            try:
                respuesta = correlacionar(payload)
            except availability.AvailabilityError:
                fallos += 1
                continue
            respuestas.append((banda, respuesta))
        if respuestas:
            return _combinar(respuestas, disponibles)
        if fallos == len(BANDAS):
            referencias_fallidas += 1
    if referencias_usadas and referencias_fallidas == len(referencias_usadas):
        raise availability.AvailabilityError(
            "No se pudo consultar el servicio de correlación."
        )
    return {
        "senal_n": 0,
        "senal_estaciones": "",
        "senal_estado": "sin_datos",
        "detalle": {},
    }


def _seleccionar(
    filas: list[dict],
    event_ids: set[str] | None,
    max_eventos: int,
    forzar: bool,
    resultados: dict[tuple[str, str], object] | None = None,
) -> list[dict]:
    if max_eventos <= 0:
        return []
    resultados = resultados or {}
    seleccionadas = []
    for fila in filas:
        if int(fila.get("total_n") or 0) <= 0:
            continue
        if event_ids is not None and fila.get("evento") not in event_ids:
            continue
        if not forzar:
            if fila.get("senal_estado") in ESTADOS_TERMINALES:
                continue
            clave = (
                _texto(fila.get("evento")),
                huella_fila(fila),
            )
            if clave in resultados:
                continue
        seleccionadas.append(fila)
        if len(seleccionadas) >= max_eventos:
            break
    return seleccionadas


def analizar(
    workspace: Path,
    fuente: str,
    *,
    event_ids: set[str] | None = None,
    max_eventos: int = MAX_EVENTOS,
    max_candidatas: int = MAX_CANDIDATAS,
    forzar: bool = False,
    correlacionar_fn=None,
    progreso=None,
) -> dict:
    """Analiza la señal de las candidatas pendientes del reporte."""
    workspace = Path(workspace)
    if event_ids is not None:
        event_ids = {
            _texto(item) for item in event_ids if _texto(item)
        }
    filas = picks_coverage.leer(workspace, fuente)
    resultados = mapa_resultados(fuente, filas)
    seleccionadas = _seleccionar(
        filas, event_ids, max_eventos, forzar, resultados
    )
    if not seleccionadas:
        return {
            "eventos": 0,
            "con_senal": 0,
            "sin_senal": 0,
            "sin_datos": 0,
            "errores": 0,
        }
    eventos = {
        _texto(evento.get("event_id")): evento
        for evento in canonical.leer_canonico(workspace, fuente)
    }
    arribos: dict[str, list[dict]] = defaultdict(list)
    for arribo in canonical.leer_arribos(workspace, fuente):
        event_id = _texto(arribo.get("event_id"))
        if event_id:
            arribos[event_id].append(arribo)
    procesados = 0
    con_senal = 0
    sin_senal = 0
    sin_datos = 0
    errores = 0
    cambios: dict[str, dict] = {}
    total_seleccionados = len(seleccionadas)
    for indice, fila in enumerate(seleccionadas, start=1):
        event_id = _texto(fila.get("evento"))
        if progreso is not None:
            progreso(indice, total_seleccionados, event_id)
        evento = eventos.get(event_id)
        if evento is None:
            continue
        try:
            resultado = analizar_evento(
                evento,
                fila.get("detalle") or [],
                arribos.get(event_id, []),
                max_candidatas=max_candidatas,
                correlacionar_fn=correlacionar_fn,
            )
        except availability.AvailabilityError:
            # No se marca el evento: queda pendiente para reintentar.
            errores += 1
            continue
        guardar_resultado(fuente, fila, resultado)
        cambios[event_id] = {
            "senal_n": resultado["senal_n"],
            "senal_estaciones": resultado["senal_estaciones"],
            "senal_estado": resultado["senal_estado"],
            "senal_actualizado": datetime.now(UTC).isoformat(),
        }
        procesados += 1
        if resultado["senal_estado"] == "sin_datos":
            sin_datos += 1
        elif resultado["senal_n"]:
            con_senal += 1
        else:
            sin_senal += 1
    if cambios:
        picks_coverage.actualizar_senales(workspace, fuente, cambios)
    completar_reporte(workspace, fuente)
    return {
        "eventos": procesados,
        "con_senal": con_senal,
        "sin_senal": sin_senal,
        "sin_datos": sin_datos,
        "errores": errores,
        "actualizado": datetime.now(UTC).isoformat(),
    }


__all__ = [
    "BANDAS",
    "MAX_CANDIDATAS",
    "MAX_EVENTOS",
    "SignalBackupError",
    "analizar",
    "analizar_evento",
    "campos_desde_resultado",
    "completar_reporte",
    "guardar_resultado",
    "guardar_resumen",
    "huella_fila",
    "huella_regla",
    "importar_reporte",
    "leer_resumen",
    "mapa_resultados",
    "resultado_evento",
    "ruta_resumen",
]
