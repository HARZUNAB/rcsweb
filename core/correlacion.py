"""Correlación de formas de onda para estaciones sin arribos.

Este módulo corre en el servicio auxiliar ``disponibilidad``, que es el único
con acceso al SDS y al recordstream. Usa ObsPy para leer y preparar las trazas,
y NumPy para las métricas de STA/LTA y correlación cruzada.

La idea es comparar una estación de referencia, que sí tiene un pick P, con
estaciones que estaban disponibles pero no fueron picadas. El resultado es un
indicio para revisión, no un pick automático.
"""

from __future__ import annotations

import io
import math
import subprocess
import time
from datetime import UTC, datetime

import numpy as np

VERSION = 1

ESTADO_CON_DATOS = "CON_DATOS"
ESTADO_SIN_DATOS = "SIN_DATOS"
ESTADO_DATOS_INSUFICIENTES = "DATOS_INSUFICIENTES"

CLASIFICACION_PODRIA = "podria_picarse"
CLASIFICACION_SENAL = "senal_detectada"
CLASIFICACION_DEBIL = "senal_debil"
CLASIFICACION_SIN_SENAL = "sin_senal"
CLASIFICACION_SIN_DATOS = "sin_datos"

ETIQUETAS = {
    CLASIFICACION_PODRIA: "Podría haberse picado",
    CLASIFICACION_SENAL: "Señal detectada (revisar)",
    CLASIFICACION_DEBIL: "Señal débil",
    CLASIFICACION_SIN_SENAL: "Sin señal clara",
    CLASIFICACION_SIN_DATOS: "Sin datos",
}

MAX_CANDIDATOS = 200
MAX_VENTANA_S = 600.0
MIN_MUESTRAS = 50


class ErrorCorrelacion(ValueError):
    """Solicitud de correlación inválida."""


def _texto(valor) -> str:
    return str(valor if valor is not None else "").strip()


def _numero(valor, defecto=None):
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return defecto
    if not math.isfinite(numero):
        return defecto
    return numero


def parse_stream(stream: str) -> tuple[str, str, str, str]:
    """Separa NET.STA.LOC.CHA y tolera localización vacía."""
    partes = _texto(stream).split(".")
    if len(partes) != 4 or not partes[0] or not partes[1] or not partes[3]:
        raise ErrorCorrelacion(f"Stream inválido: {stream!r}")
    return partes[0], partes[1], partes[2], partes[3]


def _instante(valor: str, campo: str) -> float:
    limpio = _texto(valor).replace("Z", "+00:00")
    if not limpio:
        raise ErrorCorrelacion(f"Falta {campo}.")
    try:
        instante = datetime.fromisoformat(limpio)
    except ValueError as exc:
        raise ErrorCorrelacion(f"{campo} no tiene formato ISO 8601.") from exc
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=UTC)
    return instante.timestamp()


def _formatear_instante(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")


def _obspy():
    try:
        import obspy
    except ImportError as exc:  # pragma: no cover - depende del sidecar
        raise RuntimeError(
            "ObsPy no está instalado en el servicio de disponibilidad."
        ) from exc
    return obspy


def _leer_sds(stream: str, desde: float, hasta: float):
    """Lee del SDS local con el cliente de ObsPy."""
    obspy = _obspy()
    from obspy.clients.filesystem.sds import Client

    from . import disponibilidad

    raiz = disponibilidad.raiz_sds()
    if not raiz:
        return None
    net, sta, loc, cha = parse_stream(stream)
    cliente = Client(raiz)
    try:
        st = cliente.get_waveforms(
            net,
            sta,
            loc,
            cha,
            obspy.UTCDateTime(desde),
            obspy.UTCDateTime(hasta),
        )
    except Exception:
        return None
    if not st or not len(st):
        return None
    return st


def _leer_scart(stream: str, desde: float, hasta: float):
    """Respaldo con scart cuando el cliente SDS no encuentra el stream."""
    obspy = _obspy()
    from . import disponibilidad

    scart = disponibilidad.ruta_scart()
    if not scart:
        return None
    ventana = f"{_formatear_instante(desde)}~{_formatear_instante(hasta)}"
    intentos = []
    raiz = disponibilidad.raiz_sds()
    if raiz:
        intentos.append([scart, "-d", raiz])
    url = disponibilidad.recordstream()
    if url:
        intentos.append([scart, "-I", url])
    for base in intentos:
        comando = base + ["-n", stream, "-t", ventana]
        try:
            proceso = subprocess.run(
                comando,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if proceso.returncode != 0 or not proceso.stdout:
            continue
        try:
            st = obspy.read(io.BytesIO(proceso.stdout), format="MSEED")
        except Exception:
            continue
        if len(st):
            return st
    return None


def leer_traza(stream: str, desde: float, hasta: float):
    """Lee una traza del SDS y, si falla, del recordstream."""
    st = _leer_sds(stream, desde, hasta)
    if st is None:
        st = _leer_scart(stream, desde, hasta)
    return st


def preparar_traza(st, *, fs: float, banda: tuple[float, float]):
    """Detrend, taper, bandpass y remuestreo de un Stream de ObsPy."""
    if st is None or not len(st):
        return None
    st = st.copy()
    try:
        st.merge(method=1, fill_value="interpolate")
    except Exception:
        pass
    if not len(st):
        return None
    traza = st[0].copy()
    try:
        traza.detrend("linear")
        traza.taper(0.05)
        if banda[0] > 0 and banda[1] > banda[0]:
            traza.filter(
                "bandpass",
                freqmin=banda[0],
                freqmax=banda[1],
                corners=4,
                zerophase=True,
            )
        if fs > 0 and abs(traza.stats.sampling_rate - fs) > 0.01:
            traza.resample(fs)
    except Exception:
        return None
    datos = np.asarray(traza.data, dtype=float)
    if datos.size < MIN_MUESTRAS or not np.any(np.isfinite(datos)):
        return None
    if not np.all(np.isfinite(datos)):
        datos = np.nan_to_num(datos, nan=0.0, posinf=0.0, neginf=0.0)
    inicio = float(traza.stats.starttime.timestamp)
    frecuencia = float(traza.stats.sampling_rate)
    if frecuencia <= 0:
        return None
    return {
        "datos": datos,
        "inicio": inicio,
        "fs": frecuencia,
        "stream": str(traza.id),
    }


def media_movil(datos: np.ndarray, muestras: int) -> np.ndarray:
    """Media móvil centrada al final de cada ventana, sin dependencias extra."""
    datos = np.asarray(datos, dtype=float)
    salida = np.full(datos.shape, np.nan, dtype=float)
    if muestras <= 0 or datos.size < muestras:
        return salida
    acumulado = np.concatenate(([0.0], np.cumsum(datos, dtype=float)))
    salida[muestras - 1 :] = (
        acumulado[muestras:] - acumulado[:-muestras]
    ) / float(muestras)
    return salida


def sta_lta_ratio(
    datos: np.ndarray,
    fs: float,
    sta_s: float,
    lta_s: float,
) -> np.ndarray:
    """Relación STA/LTA sobre la energía de la traza."""
    datos = np.asarray(datos, dtype=float)
    nsta = max(1, int(round(sta_s * fs)))
    nlta = max(nsta + 1, int(round(lta_s * fs)))
    energia = datos * datos
    sta = media_movil(energia, nsta)
    lta = media_movil(energia, nlta)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = sta / (lta + 1e-12)
    return ratio


def correlacion_max(
    referencia: np.ndarray,
    candidata: np.ndarray,
    fs: float,
    max_lag_s: float,
) -> tuple[float | None, float | None]:
    """Máximo CC normalizado y lag, con la candidata ya marginada.

    ``candidata`` debe empezar ``max_lag_s`` segundos antes de la alineación
    esperada y tener al menos ``len(referencia) + 2 * max_lag_s * fs`` muestras.
    """
    ref = np.asarray(referencia, dtype=float)
    cand = np.asarray(candidata, dtype=float)
    if ref.size < MIN_MUESTRAS or cand.size < ref.size:
        return None, None
    max_lag = max(1, int(round(max_lag_s * fs)))
    necesario = ref.size + 2 * max_lag
    if cand.size < necesario:
        return None, None
    ref = ref - np.nanmean(ref)
    cand = cand[:necesario] - np.nanmean(cand[:necesario])
    ref_energia = float(np.sum(ref * ref))
    if ref_energia <= 0:
        return None, None
    valores = np.correlate(cand, ref, mode="valid")
    acumulado = np.concatenate(([0.0], np.cumsum(cand * cand)))
    energia = acumulado[ref.size :] - acumulado[:-ref.size]
    denominador = np.sqrt(np.maximum(energia, 0.0)) * math.sqrt(ref_energia)
    cc = np.divide(
        valores,
        denominador,
        out=np.zeros_like(valores),
        where=denominador > 0,
    )
    if not np.any(np.isfinite(cc)):
        return None, None
    indice = int(np.argmax(np.abs(cc)))
    lag = (indice - max_lag) / float(fs)
    return float(cc[indice]), float(lag)


def max_sta_lta(
    ratio: np.ndarray,
    inicio: float,
    fs: float,
    desde: float,
    hasta: float,
) -> tuple[float | None, float | None]:
    """Máximo STA/LTA dentro de una ventana temporal."""
    ratio = np.asarray(ratio, dtype=float)
    if ratio.size == 0:
        return None, None
    tiempos = inicio + np.arange(ratio.size) / float(fs)
    mascara = (tiempos >= desde) & (tiempos <= hasta) & np.isfinite(ratio)
    if not np.any(mascara):
        return None, None
    indices = np.flatnonzero(mascara)
    posicion = int(indices[int(np.argmax(ratio[mascara]))])
    return float(ratio[posicion]), float(tiempos[posicion])


def racha_sobre_umbral(
    ratio: np.ndarray,
    inicio: float,
    fs: float,
    umbral: float,
    desde: float,
    hasta: float,
) -> float:
    """Duración de la racha continua sobre el umbral que contiene el pico."""
    ratio = np.asarray(ratio, dtype=float)
    if ratio.size == 0 or fs <= 0:
        return 0.0
    tiempos = inicio + np.arange(ratio.size) / float(fs)
    mascara = (tiempos >= desde) & (tiempos <= hasta) & np.isfinite(ratio)
    if not np.any(mascara):
        return 0.0
    indices = np.flatnonzero(mascara)
    pico = int(indices[int(np.argmax(ratio[mascara]))])
    if not np.isfinite(ratio[pico]) or ratio[pico] < umbral:
        return 0.0
    izquierda = pico
    derecha = pico
    while (
        izquierda - 1 >= 0
        and np.isfinite(ratio[izquierda - 1])
        and ratio[izquierda - 1] >= umbral
    ):
        izquierda -= 1
    while (
        derecha + 1 < ratio.size
        and np.isfinite(ratio[derecha + 1])
        and ratio[derecha + 1] >= umbral
    ):
        derecha += 1
    return (derecha - izquierda + 1) / float(fs)


def clasificar(
    *,
    cc_max: float | None,
    lag_s: float | None,
    sta_lta: float | None,
    cc_min: float,
    sta_lta_min: float,
    lag_max_s: float,
    sta_lta_racha_s: float = 0.0,
    sta_lta_persistencia_s: float = 0.0,
) -> tuple[str, str]:
    """Clasificación conservadora a partir de los dos indicadores."""
    if cc_max is None and sta_lta is None:
        return CLASIFICACION_SIN_DATOS, "No se pudo calcular la señal."
    correlacion_ok = (
        cc_max is not None
        and cc_max >= cc_min
        and lag_s is not None
        and abs(lag_s) <= lag_max_s
    )
    persistencia_ok = (
        sta_lta_persistencia_s <= 0
        or sta_lta_racha_s >= sta_lta_persistencia_s
    )
    estacion_ok = (
        sta_lta is not None
        and sta_lta >= sta_lta_min
        and persistencia_ok
    )
    if correlacion_ok and estacion_ok:
        return CLASIFICACION_PODRIA, "Correlación y STA/LTA sobre el umbral."
    if estacion_ok:
        return (
            CLASIFICACION_SENAL,
            "STA/LTA sobre el umbral en la ventana de P.",
        )
    if correlacion_ok:
        return CLASIFICACION_DEBIL, "Correlaciona, pero STA/LTA es bajo."
    return CLASIFICACION_SIN_SENAL, "Ni correlación ni STA/LTA superan el umbral."


def _ventana(traza: dict, desde: float, hasta: float):
    if traza is None:
        return None
    datos = traza["datos"]
    inicio = traza["inicio"]
    fs = traza["fs"]
    a = max(0, int(round((desde - inicio) * fs)))
    b = min(datos.size, int(round((hasta - inicio) * fs)))
    if b - a < MIN_MUESTRAS:
        return None
    return {
        "datos": datos[a:b],
        "inicio": inicio + a / fs,
        "fs": fs,
        "stream": traza["stream"],
    }


def _leer_ventana(stream: str, desde: float, hasta: float, fs: float, banda):
    if hasta <= desde:
        return None
    if hasta - desde > MAX_VENTANA_S:
        hasta = desde + MAX_VENTANA_S
    st = leer_traza(stream, desde, hasta)
    return preparar_traza(st, fs=fs, banda=banda)


def _validar(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ErrorCorrelacion("El cuerpo debe ser un objeto JSON.")
    referencia = payload.get("reference")
    if not isinstance(referencia, dict):
        raise ErrorCorrelacion("Falta reference.")
    stream_ref = _texto(referencia.get("stream"))
    parse_stream(stream_ref)
    pick_ref = _instante(referencia.get("pick_time"), "reference.pick_time")
    candidatos = payload.get("candidates")
    if not isinstance(candidatos, list) or not candidatos:
        raise ErrorCorrelacion("No hay candidates.")
    if len(candidatos) > MAX_CANDIDATOS:
        raise ErrorCorrelacion(
            f"Demasiados candidatos: {len(candidatos)} (máximo {MAX_CANDIDATOS})."
        )
    fs = _numero(payload.get("fs"), 100.0)
    if fs is None or fs < 1 or fs > 500:
        raise ErrorCorrelacion("fs debe estar entre 1 y 500 Hz.")
    banda = payload.get("band") or [1.0, 10.0]
    try:
        fmin, fmax = float(banda[0]), float(banda[1])
    except (TypeError, ValueError, IndexError) as exc:
        raise ErrorCorrelacion("band debe ser [fmin, fmax].") from exc
    if not (0 <= fmin < fmax <= fs / 2):
        raise ErrorCorrelacion("Banda inválida para la frecuencia de muestreo.")
    return {
        "stream_ref": stream_ref,
        "pick_ref": pick_ref,
        "candidatos": candidatos,
        "fs": fs,
        "banda": (fmin, fmax),
        "template_before_s": _numero(
            payload.get("template_before_s"), 1.0
        ),
        "template_after_s": _numero(payload.get("template_after_s"), 7.0),
        "candidate_before_s": _numero(
            payload.get("candidate_before_s"), 10.0
        ),
        "candidate_after_s": _numero(
            payload.get("candidate_after_s"), 30.0
        ),
        "max_lag_s": _numero(payload.get("max_lag_s"), 5.0),
        "sta_s": _numero(payload.get("sta_s"), 0.5),
        "lta_s": _numero(payload.get("lta_s"), 10.0),
        "sta_lta_before_s": _numero(
            payload.get("sta_lta_before_s"), 1.5
        ),
        "sta_lta_after_s": _numero(payload.get("sta_lta_after_s"), 4.0),
        "sta_lta_persistencia_s": _numero(
            payload.get("sta_lta_persistencia_s"), 0.0
        ),
        "cc_min": _numero(payload.get("cc_min"), 0.5),
        "sta_lta_min": _numero(payload.get("sta_lta_min"), 3.0),
    }


def analizar(payload: dict) -> dict:
    """Analiza la referencia y las candidatas; devuelve indicios por estación."""
    inicio_analisis = time.monotonic()
    params = _validar(payload)
    fs = params["fs"]
    banda = params["banda"]
    margen_ref = max(
        params["lta_s"] + params["sta_lta_before_s"],
        params["template_before_s"] + 2.0,
    )
    inicio_ref = params["pick_ref"] - margen_ref
    fin_ref = (
        params["pick_ref"]
        + max(params["template_after_s"], params["sta_lta_after_s"])
        + 2.0
    )
    traza_ref = _leer_ventana(
        params["stream_ref"], inicio_ref, fin_ref, fs, banda
    )
    if traza_ref is None:
        raise ErrorCorrelacion(
            "No se pudo leer la estación de referencia en el SDS."
        )
    template = _ventana(
        traza_ref,
        params["pick_ref"] - params["template_before_s"],
        params["pick_ref"] + params["template_after_s"],
    )
    if template is None:
        raise ErrorCorrelacion(
            "La ventana de la estación de referencia es demasiado corta."
        )
    ref_datos = template["datos"]
    max_lag = params["max_lag_s"]
    n_ref = ref_datos.size
    ratio_ref = sta_lta_ratio(
        traza_ref["datos"], fs, params["sta_s"], params["lta_s"]
    )
    sta_ref, _ = max_sta_lta(
        ratio_ref,
        traza_ref["inicio"],
        fs,
        params["pick_ref"] - params["sta_lta_before_s"],
        params["pick_ref"] + params["sta_lta_after_s"],
    )
    resultados = []
    resumen = {
        CLASIFICACION_PODRIA: 0,
        CLASIFICACION_SENAL: 0,
        CLASIFICACION_DEBIL: 0,
        CLASIFICACION_SIN_SENAL: 0,
        CLASIFICACION_SIN_DATOS: 0,
        "con_datos": 0,
        "total": 0,
    }
    for candidato in params["candidatos"]:
        if not isinstance(candidato, dict):
            continue
        stream = _texto(candidato.get("stream"))
        item = {
            "stream": stream,
            "station": _texto(candidato.get("station")),
            "distance_km": _numero(candidato.get("distance_km")),
            "expected_time": _texto(candidato.get("expected_time")),
            "status": ESTADO_SIN_DATOS,
            "clasificacion": CLASIFICACION_SIN_DATOS,
            "etiqueta": ETIQUETAS[CLASIFICACION_SIN_DATOS],
            "cc_max": None,
            "lag_s": None,
            "sta_lta_max": None,
            "sta_lta_time": None,
            "muestras": 0,
            "motivo": "",
        }
        try:
            parse_stream(stream)
            esperado = _instante(candidato.get("expected_time"), "expected_time")
        except ErrorCorrelacion as exc:
            item["motivo"] = str(exc)
            resultados.append(item)
            resumen[CLASIFICACION_SIN_DATOS] += 1
            resumen["total"] += 1
            continue
        desde = min(
            esperado
            - params["template_before_s"]
            - max_lag
            - params["candidate_before_s"],
            esperado - params["lta_s"] - params["sta_lta_before_s"] - 1.0,
        )
        hasta = max(
            esperado
            + params["template_after_s"]
            + max_lag
            + params["candidate_after_s"],
            esperado + params["sta_lta_after_s"] + 2.0,
        )
        traza = _leer_ventana(stream, desde, hasta, fs, banda)
        if traza is None:
            item["motivo"] = "No se encontraron formas de onda."
            resultados.append(item)
            resumen[CLASIFICACION_SIN_DATOS] += 1
            resumen["total"] += 1
            continue
        item["status"] = ESTADO_CON_DATOS
        item["muestras"] = int(traza["datos"].size)
        # La candidata se arma para que la alineación esperada quede en el
        # centro del margen de lag.
        inicio_cc = (
            esperado
            - params["template_before_s"]
            - max_lag
        )
        ventana_cc = _ventana(
            traza,
            inicio_cc,
            inicio_cc + (n_ref + 2 * max_lag * fs) / fs,
        )
        if ventana_cc is None:
            item["status"] = ESTADO_DATOS_INSUFICIENTES
            item["motivo"] = "Ventana insuficiente para correlacionar."
            resultados.append(item)
            resumen[CLASIFICACION_SIN_DATOS] += 1
            resumen["total"] += 1
            continue
        cc_max, lag_s = correlacion_max(
            ref_datos,
            ventana_cc["datos"],
            fs,
            max_lag,
        )
        ratio = sta_lta_ratio(
            traza["datos"], fs, params["sta_s"], params["lta_s"]
        )
        sta_max, sta_time = max_sta_lta(
            ratio,
            traza["inicio"],
            fs,
            esperado - params["sta_lta_before_s"],
            esperado + params["sta_lta_after_s"],
        )
        racha = racha_sobre_umbral(
            ratio,
            traza["inicio"],
            fs,
            params["sta_lta_min"],
            esperado - params["sta_lta_before_s"],
            esperado + params["sta_lta_after_s"],
        )
        clasificacion, motivo = clasificar(
            cc_max=cc_max,
            lag_s=lag_s,
            sta_lta=sta_max,
            cc_min=params["cc_min"],
            sta_lta_min=params["sta_lta_min"],
            lag_max_s=max_lag,
            sta_lta_racha_s=racha,
            sta_lta_persistencia_s=params["sta_lta_persistencia_s"],
        )
        item.update(
            {
                "status": ESTADO_CON_DATOS,
                "cc_max": cc_max,
                "lag_s": lag_s,
                "sta_lta_max": sta_max,
                "sta_lta_time": (
                    _formatear_instante(sta_time) if sta_time else None
                ),
                "sta_lta_racha_s": racha,
                "clasificacion": clasificacion,
                "etiqueta": ETIQUETAS[clasificacion],
                "motivo": motivo,
            }
        )
        resultados.append(item)
        resumen[clasificacion] += 1
        resumen["con_datos"] += 1
        resumen["total"] += 1
    resumen["podrian_picarse"] = resumen[CLASIFICACION_PODRIA]
    resumen["candidatas_revision"] = (
        resumen[CLASIFICACION_PODRIA] + resumen[CLASIFICACION_SENAL]
    )
    resumen["referencia_debil"] = bool(
        sta_ref is not None and sta_ref < params["sta_lta_min"]
    )
    return {
        "version": VERSION,
        "referencia": {
            "stream": params["stream_ref"],
            "pick_time": _formatear_instante(params["pick_ref"]),
            "sta_lta_max": sta_ref,
            "muestras_template": int(n_ref),
        },
        "parametros": {
            "fs": fs,
            "band": [banda[0], banda[1]],
            "template_before_s": params["template_before_s"],
            "template_after_s": params["template_after_s"],
            "max_lag_s": max_lag,
            "sta_s": params["sta_s"],
            "lta_s": params["lta_s"],
            "sta_lta_before_s": params["sta_lta_before_s"],
            "sta_lta_after_s": params["sta_lta_after_s"],
            "sta_lta_persistencia_s": params["sta_lta_persistencia_s"],
            "cc_min": params["cc_min"],
            "sta_lta_min": params["sta_lta_min"],
        },
        "resultados": resultados,
        "resumen": resumen,
        "duracion_ms": int((time.monotonic() - inicio_analisis) * 1000),
    }


__all__ = [
    "ErrorCorrelacion",
    "analizar",
    "clasificar",
    "correlacion_max",
    "media_movil",
    "parse_stream",
    "racha_sobre_umbral",
    "sta_lta_ratio",
]
