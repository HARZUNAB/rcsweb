"""Orquestación del pipeline de análisis.

Ejecuta los scripts del proyecto base como subprocesos, con el workspace del
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

from ..extensions import db
from ..models import Job, JobArtifact, JobStep
from .audit import registrar
from .results import construir_resultados
from .workspace import (
    crear_workspace,
    leer_log,
    nombre_canonico,
    preparar_entradas,
    ruta_log,
    ruta_workspace,
)

PROGRESO_RE = re.compile(r"@@PROGRESO@@\s+([0-9]*\.?[0-9]+)")
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


def _actualizar_progreso(job_id: str, indice: int, total: int, fraccion: float) -> None:
    fraccion = max(0.0, min(1.0, fraccion))
    porcentaje = int(100 * (indice + fraccion) / max(1, total))
    db.session.expire_all()
    job = db.session.get(Job, job_id)
    if job is None:
        return
    if porcentaje > (job.progress or 0):
        job.progress = min(99, porcentaje)
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
        raise PipelineError(f"No se encontró {script} en el core montado.")

    comando = [sys.executable, str(script), *paso.args]
    log.escribir("")
    log.escribir(f"=== {paso.titulo} ===")
    log.escribir("$ " + " ".join(comando))

    entorno = os.environ.copy()
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
            _actualizar_progreso(job_id, indice, total, fraccion)
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


def _verificar_eventquery(workspace: Path, nombre: str) -> None:
    ruta = workspace / "datos" / f"new_2_{nombre}"
    if not ruta.is_file():
        raise PipelineError("El catálogo de eventquery no tiene eventos válidos o no se pudo leer.")


def _verificar_seisan(workspace: Path) -> None:
    ruta = workspace / "datos" / "salida_collect.csv"
    if not ruta.is_file():
        raise PipelineError(
            "El select.out no produjo eventos analizables. Revisa el formato del archivo."
        )


def _fuentes_job(job: Job) -> list[str]:
    """Códigos de fuentes locales seleccionadas, en el orden del trabajo."""
    if job.sources:
        return [s.kind for s in job.sources if s.kind != "eventquery"]
    return sorted({archivo.kind for archivo in job.files if archivo.kind in ("seisan", "seiscomp")})


def _renombrar_repetidos(source: str):
    """Si el único local es SeisComp, repetidos.py etiqueta como 'seisan'."""

    def _renombrar(workspace: Path) -> None:
        informes = workspace / "informes"
        for sufijo in ("amplio", "estricto", "exclu"):
            origen = informes / f"rep_seisan_{sufijo}.txt"
            if origen.is_file():
                origen.replace(informes / f"rep_{source}_{sufijo}.txt")

    return _renombrar


def _verificar_seiscomp(workspace: Path) -> None:
    ruta = workspace / "datos" / "seiscomp_parametros.csv"
    if not ruta.is_file() or ruta.stat().st_size <= 1:
        raise PipelineError("La exportación de SeisComp no produjo soluciones válidas.")


def _construir_pasos(job: Job, eventquery: str, fuentes: list[str]) -> list[Paso]:
    tiene_seisan = "seisan" in fuentes
    tiene_seiscomp = "seiscomp" in fuentes
    if not tiene_seisan and not tiene_seiscomp:
        raise PipelineError("El trabajo no tiene ninguna fuente local seleccionada.")

    new2 = f"datos/new_2_{eventquery}"
    pasos = [
        Paso(
            "normalizar_eventquery",
            "Normalizar catálogo eventquery",
            "proc_query_harz_2.py",
            [eventquery, "trabajo/salida.dat"],
            verificar=lambda ws: _verificar_eventquery(ws, eventquery),
        )
    ]

    # Normalización de cada fuente local.
    if tiene_seiscomp:
        pasos.append(
            Paso(
                "convertir_seiscomp",
                "Convertir exportación SeisComp",
                "seiscomp_a_parametros.py",
                [nombre_canonico("seiscomp", job.inicio14, job.fin14)],
                verificar=_verificar_seiscomp,
            )
        )
    if tiene_seisan:
        pasos.extend(
            [
                Paso("normalizar_seisan", "Procesar select.out", "revisaselect.py"),
                Paso(
                    "armar_catalogo",
                    "Armar catálogo local",
                    "revisacollect.py",
                    verificar=_verificar_seisan,
                ),
            ]
        )

    # Comparaciones. Seisan conserva los nombres legacy (sin prefijo); SeisComp
    # usa el prefijo que ya espera cruza_nopub.py.
    if tiene_seiscomp:
        pasos.append(
            Paso(
                "comparar_seiscomp",
                "Comparar contra SeisComp",
                "compara.py",
                [new2, "datos/seiscomp_parametros.csv", "seiscomp_"],
            )
        )
    if tiene_seisan:
        pasos.append(
            Paso(
                "comparar_seisan",
                "Comparar contra Seisan",
                "compara.py",
                [new2, "datos/salida_collect.csv"],
            )
        )

    if tiene_seisan and tiene_seiscomp:
        pasos.append(
            Paso(
                "cruzar_no_publicados",
                "Cruzar no publicados entre fuentes",
                "cruza_nopub.py",
            )
        )

    if tiene_seisan:
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
                    ["datos/excluidos.csv", "datos/salida_collect.csv"],
                    condicion=_hay_csv_excluidos,
                ),
            ]
        )

    post = None
    if tiene_seisan and tiene_seiscomp:
        args_repetidos = [
            new2,
            "datos/salida_collect.csv",
            "datos/seiscomp_parametros.csv",
        ]
    elif tiene_seisan:
        args_repetidos = [new2, "datos/salida_collect.csv"]
    else:
        args_repetidos = [new2, "datos/seiscomp_parametros.csv"]
        post = _renombrar_repetidos("seiscomp")

    pasos.append(
        Paso(
            "detectar_repetidos",
            "Detectar eventos repetidos",
            "repetidos.py",
            args_repetidos,
            post=post,
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

    for clave, ruta in (
        ("catalogo_seisan", workspace / "datos" / "salida_collect.csv"),
        ("catalogo_seiscomp", workspace / "datos" / "seiscomp_parametros.csv"),
    ):
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

        eventquery = nombre_canonico("eventquery", job.inicio14, job.fin14)
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
            job.current_step = paso.titulo
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
                raise PipelineError(f"{paso.titulo} terminó con código {codigo}. Revisa el log.")
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

        construir_resultados(workspace, fuentes)
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
