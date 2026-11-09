"""Servicio HTTP de disponibilidad de formas de onda.

Corre en un contenedor aparte porque necesita ``scart``, el archivo SDS y el
recordstream de tiempo real. El contenedor web no tiene esas dependencias.

El servicio es de solo lectura: usa las mismas consultas que
``core/disponibilidad.py`` y nunca escribe en el SDS ni en SeisComp.

API:

    GET  /health
    POST /consultar

El POST recibe::

    {"event_time": "2026-10-22T00:00:00", "streams": ["AI.DSPA.02.BHZ"]}

y devuelve::

    {"results": {"AI.DSPA.02.BHZ": {"status": "CON_DATOS", ...}},
     "fuentes": ["SDS"], "duracion_ms": 123}

La cabecera ``X-RCS-Token`` debe coincidir con RCS_DISPONIBILIDAD_TOKEN cuando
esa variable está definida.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core import disponibilidad

log = logging.getLogger("rcsweb.disponibilidad")

MAX_STREAMS = 5000
MAX_BODY = 2 * 1024 * 1024
TAMANO_LOTE = 300
SEMAFORO = threading.BoundedSemaphore(2)


class ErrorConsulta(ValueError):
    """Solicitud inválida."""


def _instante(texto) -> datetime:
    if not isinstance(texto, str) or not texto.strip():
        raise ErrorConsulta("Falta event_time.")
    limpio = " ".join(texto.strip().replace("Z", "+00:00").split())
    try:
        instante = datetime.fromisoformat(limpio)
    except ValueError as exc:
        raise ErrorConsulta("event_time no tiene formato ISO 8601.") from exc
    if instante.tzinfo is not None:
        instante = instante.astimezone(UTC).replace(tzinfo=None)
    return instante


def _streams(valor) -> list[str]:
    if not isinstance(valor, list):
        raise ErrorConsulta("streams debe ser una lista.")
    limpios = []
    for item in valor:
        if not isinstance(item, str) or not item.strip():
            continue
        stream = item.strip()
        if stream not in limpios:
            limpios.append(stream)
    if not limpios:
        raise ErrorConsulta("No hay streams para consultar.")
    if len(limpios) > MAX_STREAMS:
        raise ErrorConsulta(
            f"Demasiados streams: {len(limpios)} (máximo {MAX_STREAMS})."
        )
    return limpios


def consultar(payload: dict, consultar_fn=None) -> dict:
    """Valida la solicitud y consulta la disponibilidad de los streams."""
    if not isinstance(payload, dict):
        raise ErrorConsulta("El cuerpo debe ser un objeto JSON.")
    instante = _instante(payload.get("event_time"))
    streams = _streams(payload.get("streams"))
    desde = instante - timedelta(minutes=disponibilidad.VENTANA_MINUTOS)
    hasta = instante + timedelta(minutes=disponibilidad.VENTANA_MINUTOS)

    fases: list[str] = []

    def _progreso(mensaje: str) -> None:
        fases.append(str(mensaje))

    funcion = consultar_fn or disponibilidad.consultar
    inicio = time.monotonic()
    resultados: dict = {}
    for indice in range(0, len(streams), TAMANO_LOTE):
        lote = streams[indice : indice + TAMANO_LOTE]
        if len(streams) > TAMANO_LOTE:
            fases.append(
                f"Lote {indice // TAMANO_LOTE + 1} de "
                f"{(len(streams) + TAMANO_LOTE - 1) // TAMANO_LOTE}…"
            )
        parcial = funcion(lote, desde, hasta, al_progreso=_progreso)
        resultados.update(parcial)
    duracion = int((time.monotonic() - inicio) * 1000)
    fuentes = sorted(
        {
            datos.get("source", "")
            for datos in resultados.values()
            if datos.get("source")
        }
    )
    return {
        "results": resultados,
        "fases": fases,
        "fuentes": fuentes,
        "duracion_ms": duracion,
        "desde": desde.isoformat(),
        "hasta": hasta.isoformat(),
    }


def health() -> dict:
    """Estado de las dependencias del servicio."""
    scart = disponibilidad.ruta_scart()
    sds = disponibilidad.raiz_sds()
    recordstream = disponibilidad.recordstream()
    sds_ok = bool(sds and os.path.isdir(sds))
    return {
        "ok": bool(scart and sds_ok),
        "scart": scart or "",
        "sds": sds or "",
        "sds_ok": sds_ok,
        "recordstream": recordstream or "",
        "version": 1,
    }


def _autorizado(handler: BaseHTTPRequestHandler) -> bool:
    esperado = os.environ.get("RCS_DISPONIBILIDAD_TOKEN", "").strip()
    if not esperado:
        return True
    recibido = (handler.headers.get("X-RCS-Token") or "").strip()
    return recibido == esperado


class Manejador(BaseHTTPRequestHandler):
    server_version = "RCSDisponibilidad/1"

    def log_message(self, formato, *args):  # noqa: A003 - firma de la base
        log.info("%s - %s", self.address_string(), formato % args)

    def _json(self, codigo: int, datos: dict) -> None:
        cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):  # noqa: N802 - API de BaseHTTPRequestHandler
        if self.path.split("?", 1)[0] != "/health":
            self._json(404, {"error": "Ruta no encontrada."})
            return
        try:
            self._json(200, health())
        except Exception as exc:  # noqa: BLE001 - el servicio no debe caerse
            log.exception("Error en /health")
            self._json(500, {"error": str(exc)})

    def do_POST(self):  # noqa: N802 - API de BaseHTTPRequestHandler
        if self.path.split("?", 1)[0] != "/consultar":
            self._json(404, {"error": "Ruta no encontrada."})
            return
        if not _autorizado(self):
            self._json(403, {"error": "Token inválido."})
            return
        try:
            largo = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._json(400, {"error": "Content-Length inválido."})
            return
        if largo <= 0 or largo > MAX_BODY:
            self._json(400, {"error": "Cuerpo vacío o demasiado grande."})
            return
        if not SEMAFORO.acquire(blocking=False):
            self._json(429, {"error": "Hay otra consulta en curso."})
            return
        try:
            crudo = self.rfile.read(largo)
            try:
                payload = json.loads(crudo.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                self._json(400, {"error": "JSON inválido."})
                return
            self._json(200, consultar(payload))
        except ErrorConsulta as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001 - responde sin tumbar el server
            log.exception("Error al consultar disponibilidad")
            self._json(500, {"error": str(exc)})
        finally:
            SEMAFORO.release()


def crear_servidor(host: str = "0.0.0.0", puerto: int = 8010) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, puerto), Manejador)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    host = os.environ.get("RCS_DISPONIBILIDAD_HOST", "0.0.0.0")
    puerto = int(os.environ.get("RCS_DISPONIBILIDAD_PORT", "8010"))
    servidor = crear_servidor(host, puerto)
    log.info("Disponibilidad escuchando en %s:%s", host, puerto)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
