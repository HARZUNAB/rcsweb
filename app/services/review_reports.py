"""Estado asíncrono y generación de solicitudes de revisión."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import redis
from flask import current_app

from ..domain.catalogs import canonical
from ..extensions import db
from ..models import Job, User
from . import indicios, plots, review
from .audit import registrar
from .detail import leer_filas
from .results import cargar_indice
from .review_report import generar_docx, generar_pdf
from .workspace import ruta_workspace

log = logging.getLogger(__name__)

CLAVE_INFORME = "rcs:revision"
TTL_INFORME = 24 * 3600


def _redis():
    url = current_app.config.get(
        "CELERY_RESULT_BACKEND", "redis://redis:6379/1"
    )
    return redis.Redis.from_url(
        str(url),
        decode_responses=True,
        socket_connect_timeout=0.5,
        socket_timeout=0.5,
    )


def clave_informe(report_id: str) -> str:
    return f"{CLAVE_INFORME}:{report_id}"


def guardar_estado(report_id: str, datos: dict) -> None:
    _redis().set(
        clave_informe(report_id),
        json.dumps(datos, ensure_ascii=False),
        ex=TTL_INFORME,
    )


def leer_estado(report_id: str) -> dict | None:
    try:
        texto = _redis().get(clave_informe(report_id))
    except redis.RedisError:
        return None
    if not texto:
        return None
    try:
        return json.loads(texto)
    except ValueError:
        return None


def actualizar_estado(report_id: str, **cambios) -> None:
    estado = leer_estado(report_id)
    if estado is None:
        return
    estado.update(cambios)
    try:
        guardar_estado(report_id, estado)
    except redis.RedisError:
        log.warning("No se pudo actualizar el estado del informe %s", report_id)


def borrar_estado(report_id: str) -> None:
    try:
        _redis().delete(clave_informe(report_id))
    except redis.RedisError:
        pass


def _texto(valor) -> str:
    return "" if valor is None else str(valor).strip()


def _evento_canonico(workspace: Path, fuente: str) -> dict[str, dict]:
    return {
        _texto(evento.get("event_id")): evento
        for evento in canonical.leer_canonico(workspace, fuente)
    }


def _datos_evento(
    workspace: Path,
    job_id: str,
    fuente: str,
    fila: dict,
    canonico: dict,
    archivo: str,
    catalogo_filas: list[dict],
    base_url: str,
) -> dict:
    indice = int(fila["fila_catalogo"])
    clasificados, _perfil = plots.clasificar_eventos(
        "catalogos",
        archivo,
        catalogo_filas,
        indice,
        opcion=fuente,
    )
    clasificacion = clasificados[0] if clasificados else {}
    mapa = None
    try:
        resumen = plots.resumen_mapa(
            "catalogos",
            "Revisión · "
            + (fila.get("id_evento_fuente") or fila.get("evento") or ""),
            catalogo_filas,
            indice,
            archivo,
            job_id,
        )
        mapa = plots.generar_mapa(
            workspace,
            "catalogos",
            fuente,
            archivo,
            catalogo_filas,
            indice,
            resumen=resumen,
        )
    except Exception:  # noqa: BLE001 - el informe sigue sin ese mapa
        log.exception(
            "No se pudo generar el mapa del evento %s", fila.get("evento")
        )
    return {
        "fila": fila,
        "canonico": canonico,
        "clasificacion": clasificacion,
        "evidencia": indicios.leer_detalle(
            workspace, fuente, fila.get("evento", "")
        ),
        "mapa": mapa,
        "url": (
            f"{base_url}/jobs/{job_id}/resultados/catalogos/"
            f"{fuente}/{indice}#indicios-fases"
        ),
    }


def ejecutar(report_id: str) -> dict:
    estado = leer_estado(report_id)
    if estado is None:
        return {"estado": "inexistente"}
    ruta: Path | None = None
    try:
        job_id = estado["job_id"]
        fuente = estado["fuente"]
        filas = estado.get("filas") or []
        assigned_to_id = estado.get("assigned_to_id")
        workspace = ruta_workspace(job_id)
        actualizar_estado(
            report_id,
            estado="generando",
            progreso=1,
            paso="Preparando los eventos…",
        )

        job = db.session.get(Job, job_id)
        assigned = db.session.get(User, assigned_to_id)
        if job is None or assigned is None:
            raise RuntimeError("Trabajo o analista no encontrado.")
        if assigned.role != "analista" or not assigned.active:
            raise RuntimeError("El analista asignado no está activo.")

        info = (cargar_indice(workspace).get("catalogos") or {}).get(fuente)
        if not info or not info.get("archivo"):
            raise RuntimeError("No se encontró el catálogo de la fuente.")
        archivo = info["archivo"]
        leido = leer_filas(workspace, archivo)
        if leido is None:
            raise RuntimeError("No se pudo leer el catálogo.")
        _columnas, catalogo_filas = leido
        canonicos = _evento_canonico(workspace, fuente)
        base_url = _texto(estado.get("base_url"))

        eventos = []
        total = max(1, len(filas))
        for posicion, fila in enumerate(filas, start=1):
            if fila.get("fila_catalogo") in (None, ""):
                continue
            indice = int(fila["fila_catalogo"])
            if indice < 0 or indice >= len(catalogo_filas):
                continue
            eventos.append(
                _datos_evento(
                    workspace,
                    job_id,
                    fuente,
                    fila,
                    canonicos.get(_texto(fila.get("evento")), {}),
                    archivo,
                    catalogo_filas,
                    base_url,
                )
            )
            actualizar_estado(
                report_id,
                progreso=int(90 * posicion / total),
                paso=f"Mapa {posicion} de {len(filas)}",
            )
        if not eventos:
            raise RuntimeError("No se pudo preparar ningún evento.")

        formato = estado.get("formato", "pdf")
        carpeta = workspace / "revisiones"
        carpeta.mkdir(parents=True, exist_ok=True)
        extension = "pdf" if formato == "pdf" else "docx"
        ruta = carpeta / f"{report_id}.{extension}"
        aviso = ""
        notificado = _texto(estado.get("notified_at"))
        if notificado:
            try:
                notificado = datetime.fromisoformat(notificado).strftime(
                    "%Y-%m-%d %H:%M"
                )
            except ValueError:
                pass
        datos_informe = {
            "job_id": job_id,
            "source": fuente,
            "creado_por": (
                db.session.get(User, estado.get("user_id")).username
                if db.session.get(User, estado.get("user_id")) is not None
                else ""
            ),
            "asignado": assigned.username,
            "nota": estado.get("nota", ""),
            "notified_at": notificado,
            "eventos": eventos,
        }
        actualizar_estado(
            report_id,
            progreso=92,
            paso=f"Construyendo {extension.upper()}…",
        )
        try:
            if formato == "pdf":
                generar_pdf(datos_informe, ruta)
            else:
                generar_docx(datos_informe, ruta)
        except Exception:  # noqa: BLE001 - respaldo DOCX
            if formato != "pdf":
                raise
            log.exception("No se pudo generar el PDF; se intenta DOCX")
            try:
                ruta.unlink(missing_ok=True)
            except OSError:
                pass
            extension = "docx"
            ruta = carpeta / f"{report_id}.docx"
            generar_docx(datos_informe, ruta)
            aviso = (
                "No se pudo generar el PDF. Se generó el informe en DOCX."
            )

        eventos_solicitud = []
        for evento in eventos:
            fila = evento["fila"]
            canonico = evento["canonico"] or {}
            eventos_solicitud.append(
                {
                    "evento": fila.get("evento"),
                    "id_evento_fuente": fila.get("id_evento_fuente", ""),
                    "fila_catalogo": fila.get("fila_catalogo"),
                    "fecha_hora": fila.get("fecha_hora", ""),
                    "latitude": canonico.get("latitude")
                    if canonico.get("latitude") is not None
                    else fila.get("latitud"),
                    "longitude": canonico.get("longitude")
                    if canonico.get("longitude") is not None
                    else fila.get("longitud"),
                    "depth_km": canonico.get("depth_km")
                    if canonico.get("depth_km") is not None
                    else fila.get("profundidad_km"),
                    "magnitude": canonico.get("magnitude")
                    if canonico.get("magnitude") is not None
                    else fila.get("magnitud"),
                    "magnitude_type": (
                        canonico.get("magnitude_type")
                        or ((canonico.get("raw") or {}).get("Tipo_mag."))
                        or ""
                    ),
                    "analista": fila.get("analista", ""),
                    "prioridad": fila.get("prioridad", ""),
                    "motivo": fila.get("motivo", ""),
                }
            )

        # Segunda validación: otro supervisor pudo crear una solicitud
        # mientras se generaba el PDF.
        conflictos = review.conflictos(
            job_id,
            fuente,
            [evento["evento"] for evento in eventos_solicitud],
        )
        if conflictos:
            detalle = "; ".join(
                f"{c['evento']} → solicitud #{c['solicitud_id']}"
                for c in conflictos
            )
            raise RuntimeError(
                "Los eventos ya están en revisión: " + detalle
            )

        solicitud = review.crear_solicitud(
            job_id=job_id,
            source_id=fuente,
            created_by_id=estado.get("user_id"),
            assigned_to_id=assigned_to_id,
            note=estado.get("nota", ""),
            notified_at=datetime.fromisoformat(estado["notified_at"]),
            eventos=eventos_solicitud,
            report_path=str(ruta.relative_to(workspace)),
            report_name=ruta.name,
            report_format=extension,
        )
        db.session.commit()
        actualizar_estado(
            report_id,
            estado="listo",
            progreso=100,
            paso="Solicitud creada",
            formato=extension,
            aviso=aviso,
            request_id=solicitud.id,
            url_solicitud=f"{base_url}/revisiones/{solicitud.id}",
        )
        registrar(
            "revision.crear",
            f"review:{solicitud.id}",
            {
                "job": job_id,
                "fuente": fuente,
                "eventos": len(eventos_solicitud),
                "formato": extension,
                "asignado": assigned_to_id,
            },
            user_id=estado.get("user_id"),
        )
        return {"estado": "listo", "request_id": solicitud.id}
    except Exception as exc:  # noqa: BLE001 - el estado muestra el error
        db.session.rollback()
        if ruta is not None:
            try:
                ruta.unlink(missing_ok=True)
            except OSError:
                pass
        log.exception("Error al generar la solicitud %s", report_id)
        actualizar_estado(
            report_id,
            estado="error",
            progreso=0,
            paso="Error",
            error=str(exc),
        )
        return {"estado": "error", "error": str(exc)}
