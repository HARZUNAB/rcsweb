"""Orquestación del pipeline de análisis.

Ejecuta los scripts del core incorporado como subprocesos, con el workspace del
trabajo como directorio de ejecución, y traduce las líneas ``@@PROGRESO@@`` a
progreso del job. No modifica el core: lo invoca desde su montaje read-only.
"""

from __future__ import annotations

import mimetypes
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from flask import current_app

from ..domain.catalogs import manifest as fuentes_manifest
from ..domain.catalogs.adapters.residuals import (
    enriquecer_residuales,
    hay_residuales_por_enriquecer,
)
from ..domain.catalogs.canonical import escribir_desde_csv, escribir_extensiones
from ..domain.catalogs.registry import adaptador as obtener_adaptador
from ..domain.catalogs.registry import formato as formato_info
from ..extensions import db
from ..models import Job, JobArtifact, JobStep
from .audit import registrar
from .indicios import generar_indicios
from .results import construir_resultados
from .workspace import (
    crear_workspace,
    leer_log,
    nombre_canonico,
    preparar_entradas,
    ruta_log,
    ruta_workspace,
)

PROGRESO_RE = re.compile(r"@@PROGRESO@@\s+([0-9]*\.?[0-9]+)(?:\s+(.*))?")
TIMEOUT_PASO = int(os.environ.get("PIPELINE_STEP_TIMEOUT", "1800"))


class PipelineCancelado(Exception):
    """El usuario canceló el trabajo."""


class PipelineError(Exception):
    """Un paso terminó con error o faltó un insumo."""


@dataclass
class Paso:
    clave: str
    titulo: str
    script: str | None
    args: list[str] = field(default_factory=list)
    condicion: Callable[[Path], bool] | None = None
    verificar: Callable[[Path], None] | None = None
    post: Callable[[Path], None] | None = None


class _Log:
    def __init__(self, ruta: Path):
        self.ruta = ruta
        ruta.parent.mkdir(parents=True, exist_ok=True)
        self.ruta.write_text("", encoding="utf-8")

    def escribir(self, texto: str) -> None:
        with self.ruta.open("a", encoding="utf-8") as archivo:
            archivo.write(texto.rstrip("\n") + "\n")


def _ahora() -> datetime:
    return datetime.now(UTC)


def _log(job: Job) -> None:
    """Marca el trabajo como iniciado y deja el log preparado."""
    job.status = "running"
    job.started_at = _ahora()
    job.progress = 1
    job.current_step = "Preparando el workspace"
    db.session.commit()


def _cancelado(job_id: str) -> bool:
    db.session.expire_all()
    job = db.session.get(Job, job_id)
    return job is not None and job.status == "cancelling"


def _matar(proceso: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proceso.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    try:
        proceso.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proceso.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        proceso.wait()


def _actualizar_progreso(
    job_id: str,
    indice: int,
    total: int,
    fraccion: float,
    *,
    detalle: str | None = None,
    titulo: str | None = None,
) -> None:
    """Actualiza el porcentaje global y el detalle visible de la etapa.

    El porcentaje se reparte por pasos; dentro de un paso se usa la fracción
    que informa el script. Como el porcentaje global puede quedar varios
    segundos en el mismo entero, el detalle de la etapa y su propio porcentaje
    se actualizan igual: es lo que demuestra que el proceso sigue avanzando.
    """
    fraccion = max(0.0, min(1.0, fraccion))
    porcentaje = int(100 * (indice + fraccion) / max(1, total))
    db.session.expire_all()
    job = db.session.get(Job, job_id)
    if job is None:
        return

    texto = None
    if titulo is not None:
        detalle = (detalle or "").strip()
        if not detalle:
            detalle = f"{int(fraccion * 100)} % del paso"
        texto = f"{titulo} · {detalle}"[:80]

    cambio = False
    if porcentaje > (job.progress or 0):
        job.progress = min(99, porcentaje)
        cambio = True
    if texto and job.current_step != texto:
        job.current_step = texto
        cambio = True
    if cambio:
        db.session.commit()


def _ejecutar_paso(
    paso: Paso,
    workspace: Path,
    job_id: str,
    indice: int,
    total: int,
    log: _Log,
) -> int:
    if paso.script is None:
        return 0

    core = Path(current_app.config["RCS_CORE_PATH"])
    script = core / paso.script
    if not script.is_file():
        raise PipelineError(f"No se encontró {script} en el core incorporado.")

    comando = [sys.executable, str(script), *paso.args]
    log.escribir("")
    log.escribir(f"=== {paso.titulo} ===")
    log.escribir("$ " + " ".join(comando))

    entorno = os.environ.copy()
    entorno["RCS_CORE_DATA"] = str(
        current_app.config.get("RCS_CORE_DATA", core.parent / "core_data")
    )
    entorno.update(
        {
            "RV_PROG": "1",
            "RV_ENTREGABLES": "1",
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )

    proceso = subprocess.Popen(
        comando,
        cwd=str(workspace),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=entorno,
        start_new_session=True,
    )

    cola: queue.Queue[str | None] = queue.Queue()

    def lector() -> None:
        try:
            for linea in proceso.stdout or ():
                cola.put(linea)
        finally:
            cola.put(None)

    threading.Thread(target=lector, daemon=True).start()

    inicio = time.monotonic()
    while True:
        try:
            linea = cola.get(timeout=0.5)
        except queue.Empty:
            if _cancelado(job_id):
                _matar(proceso)
                raise PipelineCancelado
            if time.monotonic() - inicio > TIMEOUT_PASO:
                _matar(proceso)
                raise PipelineError(f"{paso.titulo} superó el tiempo máximo ({TIMEOUT_PASO} s).")
            continue

        if linea is None:
            break

        coincidencia = PROGRESO_RE.search(linea)
        if coincidencia:
            try:
                fraccion = float(coincidencia.group(1))
            except ValueError:
                continue
            _actualizar_progreso(
                job_id,
                indice,
                total,
                fraccion,
                detalle=coincidencia.group(2),
                titulo=paso.titulo,
            )
            continue

        log.escribir(linea.rstrip("\n"))

    codigo = proceso.wait()
    if _cancelado(job_id):
        raise PipelineCancelado
    return codigo


def _hay_excluidos(workspace: Path) -> bool:
    ruta = workspace / "informes" / "excluidos.txt"
    return ruta.is_file() and ruta.stat().st_size > 0


def _hay_csv_excluidos(workspace: Path) -> bool:
    ruta = workspace / "datos" / "excluidos.csv"
    return ruta.is_file() and ruta.stat().st_size > 0


def _fuentes_job(job: Job) -> list[tuple[str, str, str]]:
    """(source_id, formato, alias) de las fuentes locales, principal primero."""
    if job.sources:
        referencia = fuentes_manifest.referencia().id
        locales = [
            (
                source.kind,
                fuentes_manifest.formato_de(source.kind)
                or source.format_efectivo,
                source.alias_mostrado,
                source.priority,
                source.role,
            )
            for source in job.sources
            if source.kind != referencia and fuentes_manifest.es_local(source.kind)
        ]
        locales.sort(
            key=lambda item: (
                0 if item[4] == "local_principal" else 1,
                item[3],
                item[1],
            )
        )
        return [(sid, fmt, alias) for sid, fmt, alias, _prioridad, _rol in locales]
    return [
        (
            archivo.kind,
            fuentes_manifest.formato_de(archivo.kind),
            archivo.kind,
        )
        for archivo in job.files
        if fuentes_manifest.es_local(archivo.kind)
    ]


def _normalizar_fuentes(fuentes) -> list[tuple[str, str, str]]:
    if not fuentes:
        return []
    if isinstance(fuentes[0], str):
        return [
            (codigo, fuentes_manifest.formato_de(codigo), codigo)
            for codigo in fuentes
        ]
    return [
        (sid, fuentes_manifest.formato_de(sid) or fmt, alias)
        for sid, fmt, alias in fuentes
    ]


def _planes_a_pasos(
    adapter,
    source_id: str,
    formato: str,
    job: Job,
    eventquery: str,
    *,
    es_referencia: bool = False,
) -> list[Paso]:
    adapter.source_id = source_id
    planes = adapter.pasos(job, eventquery)
    pasos = []
    for indice, plan in enumerate(planes):
        post = plan.post
        if indice == len(planes) - 1:

            def _post(
                workspace,
                _post=post,
                _adapter=adapter,
                _source_id=source_id,
                _formato=formato,
                _es_referencia=es_referencia,
            ) -> None:
                if _post is not None:
                    _post(workspace)
                raiz = Path(workspace)
                ruta = raiz / _adapter.catalogo(job, eventquery)
                try:
                    crudo = formato_info(_formato).archivo.format(
                        inicio=job.inicio14, fin=job.fin14
                    )
                except (KeyError, ValueError):
                    crudo = ""
                escribir_desde_csv(
                    raiz,
                    _source_id,
                    _formato,
                    ruta,
                    es_referencia=_es_referencia,
                    ruta_cruda=(raiz / crudo) if crudo else None,
                )
                try:
                    extensiones = _adapter.extensiones(job, eventquery, raiz)
                except (AttributeError, ValueError):
                    extensiones = {}
                if extensiones:
                    escribir_extensiones(
                        raiz,
                        _source_id,
                        _formato,
                        extensiones,
                        radio_km=getattr(job, "station_radius_km", None),
                    )

            post = _post

        pasos.append(
            Paso(
                plan.clave,
                plan.titulo,
                plan.script,
                plan.args,
                plan.condicion,
                plan.verificar,
                post,
            )
        )
    return pasos


def _renombrar_repetidos(source: str, prefijo_core: str | None = None):
    """Renombra las salidas de repetidos al id real de la fuente."""
    prefijo_core = prefijo_core or source

    def _renombrar(workspace: Path) -> None:
        informes = workspace / "informes"
        for sufijo in ("amplio", "estricto", "exclu"):
            origen = informes / f"rep_{prefijo_core}_{sufijo}.txt"
            if origen.is_file():
                destino = informes / f"rep_{source}_{sufijo}.txt"
                if origen != destino:
                    origen.replace(destino)

    return _renombrar


def _renombrar_varias(renombres: list[tuple[str, str]]):
    funciones = [_renombrar_repetidos(source, prefijo) for source, prefijo in renombres]

    def _renombrar(workspace: Path) -> None:
        for funcion in funciones:
            funcion(workspace)

    return _renombrar


def _residuales_habilitados() -> bool:
    try:
        return bool(current_app.config.get("RCS_ENRIQUECER_RESIDUALES", True))
    except RuntimeError:
        valor = os.environ.get("RCS_ENRIQUECER_RESIDUALES", "1")
        return valor.strip().lower() not in {"0", "false", "no", "off"}


def _construir_pasos(job: Job, eventquery: str, fuentes) -> list[Paso]:
    fuentes = _normalizar_fuentes(fuentes)
    if not fuentes:
        raise PipelineError("El trabajo no tiene ninguna fuente local seleccionada.")

    referencia = fuentes_manifest.referencia()
    pasos = _planes_a_pasos(
        obtener_adaptador(referencia.format),
        referencia.id,
        referencia.format,
        job,
        eventquery,
        es_referencia=True,
    )
    locales = []
    for source_id, formato, alias in fuentes:
        adapter = obtener_adaptador(formato)
        pasos.extend(_planes_a_pasos(adapter, source_id, formato, job, eventquery))
        locales.append((source_id, formato, alias, adapter))

    if _residuales_habilitados():
        pasos.append(
            Paso(
                "enriquecer_residuales",
                "Enriquecer residuales locales",
                None,
                condicion=hay_residuales_por_enriquecer,
                post=enriquecer_residuales,
            )
        )

    new2 = f"datos/new_2_{eventquery}"
    for source_id, _formato, alias, adapter in locales:
        prefijo = adapter.prefijo_salida(source_id)
        pasos.append(
            Paso(
                f"comparar_{source_id}",
                f"Comparar contra {alias}",
                "compara.py",
                [
                    new2,
                    adapter.catalogo(job, eventquery),
                    prefijo,
                ],
            )
        )

    tipos = {adapter.tipo for _sid, _fmt, _alias, adapter in locales}
    if len(locales) == 2 and tipos == {"select", "export"}:
        pasos.append(
            Paso(
                "cruzar_no_publicados",
                "Cruzar no publicados entre fuentes",
                "cruza_nopub.py",
            )
        )

    for _source_id, _formato, _alias, adapter in locales:
        if "excluidos" not in adapter.capacidades:
            continue
        catalogo = adapter.catalogo(job, eventquery)
        pasos.extend(
            [
                Paso(
                    "revisar_excluidos",
                    "Revisar eventos excluidos",
                    "revisaexcluidos.py",
                    condicion=_hay_excluidos,
                ),
                Paso(
                    "repetidos_excluidos",
                    "Detectar repetidos en excluidos",
                    "repetidosexclu.py",
                    ["datos/excluidos.csv", catalogo],
                    condicion=_hay_csv_excluidos,
                ),
            ]
        )

    args_repetidos = [new2]
    prefijos = []
    for source_id, _formato, _alias, adapter in locales:
        args_repetidos.append(adapter.catalogo(job, eventquery))
        prefijos.append(source_id)
    args_repetidos.append("--prefijos=" + ",".join(prefijos))

    def _generar_indicios(workspace: Path) -> None:
        generar_indicios(
            workspace,
            [fuente[0] for fuente in fuentes],
            job_id=job.id,
        )

    pasos.append(
        Paso(
            "generar_indicios",
            "Generar indicios de fases",
            None,
            post=_generar_indicios,
        )
    )

    pasos.append(
        Paso(
            "detectar_repetidos",
            "Detectar eventos repetidos",
            "repetidos.py",
            args_repetidos,
        )
    )
    return pasos

def _registrar_artefactos(job: Job, workspace: Path) -> None:
    for viejo in list(job.artifacts):
        db.session.delete(viejo)
    db.session.commit()

    candidatos: list[tuple[str, Path]] = []
    for carpeta, tipo in (("resultados", "resultado"), ("descargas", "entregable")):
        base = workspace / carpeta
        if not base.is_dir():
            continue
        for ruta in sorted(base.rglob("*")):
            if ruta.is_file() and ruta.name != "indice.json":
                candidatos.append((tipo, ruta))

    referencia = fuentes_manifest.referencia()
    nombre_ref = nombre_canonico(referencia.id, job.inicio14, job.fin14)
    for definicion in fuentes_manifest.fuentes():
        adapter = obtener_adaptador(definicion.format)
        adapter.source_id = definicion.id
        ruta = workspace / adapter.catalogo(job, nombre_ref)
        if ruta.is_file():
            candidatos.append(("catalogo", ruta))
    for ruta in sorted((workspace / "datos").glob("new_2_*.csv")):
        candidatos.append(("catalogo", ruta))

    vistos: set[str] = set()
    for tipo, ruta in candidatos:
        relativa = str(ruta.relative_to(workspace))
        if relativa in vistos:
            continue
        tamano = ruta.stat().st_size
        # Los entregables vacíos (por ejemplo revisar.txt sin observaciones) no
        # se ofrecen como descarga.
        if tipo == "entregable" and tamano == 0:
            continue
        vistos.add(relativa)
        mime = mimetypes.guess_type(ruta.name)[0] or "application/octet-stream"
        db.session.add(
            JobArtifact(
                job_id=job.id,
                tipo=tipo,
                ruta=relativa,
                mime=mime,
                size=tamano,
            )
        )
    db.session.commit()


def _terminar(job: Job, estado: str, *, error: str | None = None, paso: str | None = None) -> None:
    job.status = estado
    job.finished_at = _ahora()
    if estado == "done":
        job.progress = 100
        job.current_step = "Terminado"
    elif estado == "cancelled":
        job.current_step = "Cancelado"
    else:
        job.current_step = paso or "Error"
    job.error = error
    db.session.commit()

    if estado == "done":
        registrar(
            "job.done",
            entity=job.id,
            meta={"pasos": len(job.steps), "progreso": job.progress},
            user_id=job.created_by_id,
        )
    elif estado == "failed":
        registrar(
            "job.failed",
            entity=job.id,
            meta={"error": error, "paso": paso},
            user_id=job.created_by_id,
        )
    elif estado == "cancelled":
        registrar(
            "job.cancelled",
            entity=job.id,
            meta={"paso": paso},
            user_id=job.created_by_id,
        )


def ejecutar_pipeline(job_id: str) -> dict:
    """Ejecuta el pipeline completo de un trabajo.

    Se llama desde la tarea Celery, dentro del contexto de la aplicación.
    """
    job = db.session.get(Job, job_id)
    if job is None:
        return {"job_id": job_id, "estado": "inexistente"}
    if job.status not in ("queued", "cancelling"):
        return {"job_id": job_id, "estado": job.status}
    if job.status == "cancelling":
        _terminar(job, "cancelled")
        return {"job_id": job_id, "estado": "cancelled"}

    workspace = crear_workspace(job_id)
    log = _Log(ruta_log(workspace))
    log.escribir(f"Trabajo {job_id}")
    log.escribir(f"Período: {job.inicio14} → {job.fin14}")

    try:
        preparar_entradas(job)
        _log(job)

        referencia = fuentes_manifest.referencia()
        eventquery = nombre_canonico(
            referencia.id, job.inicio14, job.fin14
        )
        fuentes = _fuentes_job(job)
        pasos = _construir_pasos(job, eventquery, fuentes)

        # Se crean todas las filas de pasos al inicio para que la UI muestre el
        # plan completo desde el primer segundo.
        for orden, paso in enumerate(pasos, start=1):
            db.session.add(
                JobStep(
                    job_id=job.id,
                    orden=orden,
                    script=paso.clave,
                    status="pending",
                    log_path="logs/pipeline.log",
                )
            )
        db.session.commit()

        total = len(pasos)
        for indice, paso in enumerate(pasos):
            if _cancelado(job_id):
                raise PipelineCancelado

            fila = db.session.execute(
                db.select(JobStep).filter_by(job_id=job.id, orden=indice + 1).limit(1)
            ).scalar_one()
            fila.status = "running"
            fila.started_at = _ahora()
            job.current_step = f"{paso.titulo} ({indice + 1}/{total})"[:80]
            job.progress = max(job.progress, int(100 * indice / total))
            db.session.commit()

            if paso.condicion is not None and not paso.condicion(workspace):
                fila.status = "skipped"
                fila.finished_at = _ahora()
                log.escribir(f"[omitido] {paso.titulo}")
                db.session.commit()
                _actualizar_progreso(job_id, indice + 1, total, 0.0)
                continue

            codigo = _ejecutar_paso(paso, workspace, job_id, indice, total, log)
            fila.exit_code = codigo
            fila.finished_at = _ahora()
            if codigo != 0:
                raise PipelineError(f"{paso.titulo} terminó con código {codigo}. Revise el registro.")
            if paso.verificar is not None:
                paso.verificar(workspace)
            if paso.post is not None:
                paso.post(workspace)
            fila.status = "done"
            db.session.commit()
            _actualizar_progreso(job_id, indice + 1, total, 0.0)

        job.current_step = "Preparando resultados"
        job.progress = max(job.progress, 95)
        db.session.commit()

        construir_resultados(workspace, [fuente[0] for fuente in fuentes])
        _registrar_artefactos(job, workspace)
        log.escribir("")
        log.escribir("Pipeline terminado correctamente.")
        _terminar(job, "done")
        return {"job_id": job_id, "estado": "done"}

    except PipelineCancelado:
        log.escribir("")
        log.escribir("Trabajo cancelado por el usuario.")
        _terminar(job, "cancelled")
        return {"job_id": job_id, "estado": "cancelled"}

    except Exception as exc:  # noqa: BLE001 - se informa al usuario
        log.escribir("")
        log.escribir(f"ERROR: {exc}")
        _terminar(job, "failed", error=str(exc), paso=job.current_step)
        return {"job_id": job_id, "estado": "failed", "error": str(exc)}


def ultimas_lineas(job: Job, max_lineas: int = 200) -> list[str]:
    return leer_log(ruta_workspace(job.id), max_lineas=max_lineas)


def borrar_workspace(job_id: str) -> None:
    shutil.rmtree(ruta_workspace(job_id), ignore_errors=True)
