"""Consulta y caché de disponibilidad de formas de onda.

La consulta real la hace el servicio auxiliar ``disponibilidad``, que es el
único que tiene acceso a ``scart``, al SDS y al recordstream. Este módulo:

- arma la lista de streams de un evento;
- llama al servicio por HTTP;
- aplica el resultado a las filas de "Sin arribos";
- guarda y lee una caché por trabajo y fuente.
"""

from __future__ import annotations

import fcntl
import json
from datetime import UTC, datetime
from pathlib import Path

import redis
import requests
from flask import current_app

ESTADO_CON_DATOS = "CON_DATOS"
ESTADO_SIN_DATOS = "SIN_DATOS"
ESTADO_NO_CONSULTADO = "NO_CONSULTADO"

FUENTE_SDS = "SDS"
FUENTE_RECORDSTREAM = "RECORDSTREAM"

CACHE = "disponibilidad.jsonl"

CLAVE_TAREA = "rcs:disponibilidad"
TAREA_TTL = 15 * 60


class AvailabilityError(RuntimeError):
    """No se pudo consultar el servicio de disponibilidad."""


def _redis():
    url = _config("CELERY_RESULT_BACKEND", "redis://redis:6379/1")
    return redis.Redis.from_url(
        str(url),
        decode_responses=True,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
    )


def clave_tarea(job_id: str, event_id: str, vista: str = "") -> str:
    return f"{CLAVE_TAREA}:{job_id}:{event_id}:{vista or 'exportada'}"


def tarea_en_curso(job_id: str, event_id: str, vista: str = "") -> str:
    """Task id de una consulta en curso, o cadena vacía."""
    if not job_id or not event_id:
        return ""
    try:
        return _redis().get(clave_tarea(job_id, event_id, vista)) or ""
    except redis.RedisError:
        return ""


def registrar_tarea(
    job_id: str, event_id: str, task_id: str, vista: str = ""
) -> tuple[str, bool]:
    """Registra la tarea si no había otra. Devuelve (task_id, creada)."""
    if not job_id or not event_id or not task_id:
        return task_id, True
    try:
        cliente = _redis()
        clave = clave_tarea(job_id, event_id, vista)
        creada = bool(cliente.set(clave, task_id, nx=True, ex=TAREA_TTL))
        if creada:
            return task_id, True
        existente = cliente.get(clave) or task_id
        return existente, False
    except redis.RedisError:
        # Sin Redis no podemos deduplicar; Celery tampoco podrá encolar.
        return task_id, True


def limpiar_tarea(job_id: str, event_id: str, vista: str = "") -> None:
    if not job_id or not event_id:
        return
    try:
        _redis().delete(clave_tarea(job_id, event_id, vista))
    except redis.RedisError:
        pass


def _config(nombre: str, defecto=""):
    try:
        return current_app.config.get(nombre, defecto)
    except RuntimeError:
        return defecto


def configurada() -> bool:
    """True si el servicio auxiliar está configurado en este entorno."""
    return bool(_config("RCS_DISPONIBILIDAD_URL", ""))


def _url() -> str:
    return str(_config("RCS_DISPONIBILIDAD_URL", "")).rstrip("/")


def _tiempo_espera() -> int:
    try:
        return int(_config("RCS_DISPONIBILIDAD_TIMEOUT", 240))
    except (TypeError, ValueError):
        return 240


def max_estaciones() -> int:
    """Máximo de estaciones que se consultan por defecto."""
    try:
        return max(1, int(_config("RCS_DISPONIBILIDAD_MAX_ESTACIONES", 150)))
    except (TypeError, ValueError):
        return 150


def max_streams() -> int:
    """Máximo duro de streams por consulta."""
    try:
        return max(1, int(_config("RCS_DISPONIBILIDAD_MAX_STREAMS", 5000)))
    except (TypeError, ValueError):
        return 5000


def vista_clave(
    *,
    ampliado: str = "",
    radio_km=None,
    cerca_km=50.0,
    solo_cercanas: bool = False,
    disponibles: bool = False,
    todas: bool = False,
) -> str:
    """Clave de vista para separar consultas con filtros distintos."""
    radio = f"{float(radio_km):g}" if radio_km is not None else "all"
    cerca = f"{float(cerca_km):g}" if cerca_km is not None else "50"
    return ":".join(
        [
            ampliado or "exportada",
            "todas" if todas else "auto",
            f"r{radio}",
            f"c{cerca}",
            "solo" if solo_cercanas else "todos",
            "disp" if disponibles else "nodisp",
        ]
    )


def _streams_de_fila(fila: dict) -> list[str]:
    valor = fila.get("_streams")
    if isinstance(valor, list):
        return [str(item).strip() for item in valor if str(item).strip()]
    texto = str(fila.get("streams_ids") or "")
    return [item.strip() for item in texto.split(";") if item.strip()]


def streams_de_filas(filas: list[dict]) -> list[str]:
    """Todos los streams vigentes de las filas, sin repetir y en orden."""
    salida: list[str] = []
    for fila in filas:
        for stream in _streams_de_fila(fila):
            if stream not in salida:
                salida.append(stream)
    return salida


def consultar(event_time: str, streams: list[str]) -> dict:
    """Consulta el servicio auxiliar y devuelve el resultado por stream."""
    if not configurada():
        raise AvailabilityError(
            "La consulta de formas de onda no está configurada en este entorno."
        )
    if not streams:
        raise AvailabilityError("No hay streams para consultar.")
    encabezados = {"Content-Type": "application/json"}
    token = str(_config("RCS_DISPONIBILIDAD_TOKEN", "")).strip()
    if token:
        encabezados["X-RCS-Token"] = token
    try:
        respuesta = requests.post(
            f"{_url()}/consultar",
            json={"event_time": event_time, "streams": streams},
            headers=encabezados,
            timeout=_tiempo_espera(),
        )
    except requests.RequestException as exc:
        raise AvailabilityError(
            "No se pudo conectar con el servicio de disponibilidad."
        ) from exc
    if respuesta.status_code == 429:
        raise AvailabilityError(
            "Hay otra consulta de disponibilidad en curso. Intente nuevamente."
        )
    if respuesta.status_code != 200:
        detalle = ""
        try:
            detalle = str(respuesta.json().get("error") or "")
        except ValueError:
            detalle = respuesta.text[:200]
        raise AvailabilityError(
            detalle or "El servicio de disponibilidad devolvió un error."
        )
    try:
        datos = respuesta.json()
    except ValueError as exc:
        raise AvailabilityError(
            "El servicio de disponibilidad devolvió una respuesta inválida."
        ) from exc
    resultados = datos.get("results")
    if not isinstance(resultados, dict):
        raise AvailabilityError(
            "El servicio de disponibilidad no devolvió resultados."
        )
    return resultados


def _texto_formas_onda(estado: str, fuente: str) -> str:
    if estado == ESTADO_CON_DATOS:
        if fuente == FUENTE_SDS:
            return "SDS"
        if fuente == FUENTE_RECORDSTREAM:
            return "Tiempo real"
        return "Con datos"
    if estado == ESTADO_SIN_DATOS:
        return "Sin datos"
    return "No consultado"


def _texto_evidencia(estado: str, fuente: str, actividad) -> str:
    if estado == ESTADO_CON_DATOS:
        if fuente == FUENTE_SDS:
            return "Verificado (SDS)"
        if fuente == FUENTE_RECORDSTREAM:
            return "Verificado (tiempo real)"
        return "Verificado"
    try:
        activa = float(actividad) > 0
    except (TypeError, ValueError):
        activa = False
    if activa:
        return "Indicio (actividad)"
    if estado == ESTADO_SIN_DATOS:
        return "Sin evidencia"
    return "Sin consultar"


def texto_formas_onda(estado: str, fuente: str = "") -> str:
    return _texto_formas_onda(estado, fuente)


def texto_evidencia(estado: str, fuente: str = "", actividad=None) -> str:
    return _texto_evidencia(estado, fuente, actividad)


def categoria_evidencia(estado: str, evidencia: str = "") -> str:
    """Categoría visual: verificado, indicio, sin_evidencia o normal."""
    if estado == ESTADO_CON_DATOS:
        return "verificado"
    if str(evidencia).startswith("Indicio"):
        return "indicio"
    if estado == ESTADO_SIN_DATOS:
        return "sin_evidencia"
    return "normal"


def _aplicar_entrada(fila: dict, entrada: dict | None) -> None:
    entrada = entrada or {}
    estado = str(entrada.get("status") or ESTADO_NO_CONSULTADO)
    fuente = str(entrada.get("source") or "")
    fila["_estado_disponibilidad"] = estado
    fila["_fuente_disponibilidad"] = fuente
    fila["_stream_disponible"] = str(
        entrada.get("_stream") or entrada.get("stream") or ""
    )
    fila["formas_onda"] = _texto_formas_onda(estado, fuente)
    fila["evidencia"] = _texto_evidencia(
        estado, fuente, fila.get("actividad_ventana")
    )
    fila["_categoria"] = categoria_evidencia(estado, fila["evidencia"])
    fila["disponible_no_usada"] = estado == ESTADO_CON_DATOS
    fila["disponible"] = (
        "Sí"
        if estado == ESTADO_CON_DATOS
        else "No"
        if estado == ESTADO_SIN_DATOS
        else "—"
    )
    fila["cobertura_desde"] = str(
        entrada.get("desde") or entrada.get("coverage_from") or ""
    )
    fila["cobertura_hasta"] = str(
        entrada.get("hasta") or entrada.get("coverage_to") or ""
    )
    fila["cobertura"] = (
        f"{fila['cobertura_desde']} → {fila['cobertura_hasta']}"
        if fila["cobertura_desde"] or fila["cobertura_hasta"]
        else ""
    )


def _entrada_de_fila(fila: dict, resultados: dict) -> dict | None:
    """Primera entrada con datos entre los streams vigentes de la fila."""
    for stream in _streams_de_fila(fila):
        datos = resultados.get(stream)
        if datos and datos.get("status") == ESTADO_CON_DATOS:
            return dict(datos, _stream=stream)
    for stream in _streams_de_fila(fila):
        datos = resultados.get(stream)
        if datos and datos.get("status") == ESTADO_SIN_DATOS:
            return dict(datos, _stream=stream)
    return None


def aplicar_a_filas(filas: list[dict], resultados: dict) -> dict:
    """Aplica los resultados del servicio a las filas y resume el resultado."""
    con_datos = 0
    sin_datos = 0
    no_consultado = 0
    for fila in filas:
        entrada = _entrada_de_fila(fila, resultados)
        _aplicar_entrada(fila, entrada)
        estado = fila.get("_estado_disponibilidad")
        if estado == ESTADO_CON_DATOS:
            con_datos += 1
        elif estado == ESTADO_SIN_DATOS:
            sin_datos += 1
        else:
            no_consultado += 1
    return {
        "estaciones": len(filas),
        "con_datos": con_datos,
        "sin_datos": sin_datos,
        "no_consultado": no_consultado,
    }


def ruta_cache(workspace: Path, source_id: str) -> Path:
    return workspace / "catalogo" / source_id / CACHE


def leer_cache(workspace: Path, source_id: str, event_id: str) -> dict:
    """Disponibilidad cacheada de un evento, por (red, estación)."""
    ruta = ruta_cache(workspace, source_id)
    if not ruta.is_file():
        return {}
    salida = {}
    with ruta.open(encoding="utf-8") as archivo:
        for linea in archivo:
            if not linea.strip():
                continue
            try:
                registro = json.loads(linea)
            except ValueError:
                continue
            if str(registro.get("event_id") or "") != str(event_id):
                continue
            clave = (
                str(registro.get("network") or ""),
                str(registro.get("station") or ""),
            )
            salida[clave] = registro
    return salida


def aplicar_cache(filas: list[dict], cache: dict) -> None:
    """Superpone la disponibilidad cacheada a las filas de sin arribos."""
    for fila in filas:
        clave = (str(fila.get("red") or ""), str(fila.get("estacion") or ""))
        _aplicar_entrada(fila, cache.get(clave))


def _registro(fila: dict, event_id: str) -> dict:
    estado = str(fila.get("_estado_disponibilidad") or ESTADO_NO_CONSULTADO)
    return {
        "event_id": event_id,
        "network": str(fila.get("red") or ""),
        "station": str(fila.get("estacion") or ""),
        "stream": str(
            fila.get("_stream_disponible")
            or next(iter(_streams_de_fila(fila)), "")
        ),
        "status": estado,
        "source": str(fila.get("_fuente_disponibilidad") or ""),
        "coverage_from": str(fila.get("cobertura_desde") or ""),
        "coverage_to": str(fila.get("cobertura_hasta") or ""),
        "activity_window": fila.get("actividad_ventana"),
        "checked_at": datetime.now(UTC).isoformat(),
    }


def guardar_cache(
    workspace: Path,
    source_id: str,
    event_id: str,
    filas: list[dict],
) -> Path:
    """Reemplaza la caché del evento y conserva la de los demás eventos."""
    ruta = ruta_cache(workspace, source_id)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    bloqueo = ruta.with_name(f"{CACHE}.lock")
    with bloqueo.open("a+") as candado:
        fcntl.flock(candado, fcntl.LOCK_EX)
        try:
            conservadas = []
            if ruta.is_file():
                with ruta.open(encoding="utf-8") as archivo:
                    for linea in archivo:
                        if not linea.strip():
                            continue
                        try:
                            registro = json.loads(linea)
                        except ValueError:
                            continue
                        if str(registro.get("event_id") or "") == str(event_id):
                            continue
                        conservadas.append(registro)
            nuevas = [_registro(fila, event_id) for fila in filas]
            temporal = ruta.with_name(f"{CACHE}.tmp")
            with temporal.open("w", encoding="utf-8") as archivo:
                for registro in conservadas + nuevas:
                    archivo.write(
                        json.dumps(registro, ensure_ascii=False) + "\n"
                    )
            temporal.replace(ruta)
        finally:
            fcntl.flock(candado, fcntl.LOCK_UN)
    return ruta
