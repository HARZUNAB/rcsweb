"""Adquisición de catálogos por SSH/SCP y creación del trabajo."""

from __future__ import annotations

import hashlib
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from flask import current_app

from ..extensions import db
from ..models import (
    CatalogRequest,
    CatalogRequestFile,
    Job,
    JobFile,
    JobSource,
    nuevo_uuid,
)
from .audit import registrar
from .queue import encolar_trabajo
from .sources import fuente
from .validators import validar_fuente
from .workspace import crear_workspace

SUBDIRECTORIOS = ("files", "logs", "trabajo", "inputs")


class _Log:
    def __init__(self, ruta: Path):
        self.ruta = ruta
        ruta.parent.mkdir(parents=True, exist_ok=True)
        self.ruta.write_text("", encoding="utf-8")

    def escribir(self, texto: str) -> None:
        with self.ruta.open("a", encoding="utf-8") as archivo:
            archivo.write(str(texto).rstrip("\n") + "\n")


def ruta_solicitud(request_id: str) -> Path:
    raiz = Path(current_app.config["WORKSPACE_ROOT"]).resolve()
    return raiz / "solicitudes" / str(request_id)


def preparar_workspace(request_id: str) -> Path:
    workspace = ruta_solicitud(request_id)
    for nombre in SUBDIRECTORIOS:
        (workspace / nombre).mkdir(parents=True, exist_ok=True)
    return workspace


def log_solicitud(request_id: str, max_lineas: int = 200) -> list[str]:
    ruta = ruta_solicitud(request_id) / "logs" / "fetch.log"
    if not ruta.is_file():
        return []
    try:
        lineas = ruta.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lineas[-max_lineas:]


def _sha256(ruta: Path) -> str:
    digest = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            digest.update(bloque)
    return digest.hexdigest()


def _cargar_traer_catalogos():
    core = Path(current_app.config["RCS_CORE_PATH"])
    if str(core) not in sys.path:
        sys.path.insert(0, str(core))
    import traer_catalogos as tc  # type: ignore

    return tc


PREFIJO_LOCALE_REMOTO = (
    'RCS_LOCALE=""; '
    "for loc in C.UTF-8 en_US.UTF-8 es_CL.UTF-8 "
    '$(locale -a 2>/dev/null | grep -iE "utf-?8"); do '
    'if [ "$(LC_ALL=$loc locale charmap 2>/dev/null)" = "UTF-8" ]; then '
    "RCS_LOCALE=$loc; break; fi; done; "
    'if [ -z "$RCS_LOCALE" ]; then '
    'echo "[X] No hay locale UTF-8 en el servidor remoto"; exit 1; fi; '
    "export LC_ALL=$RCS_LOCALE LANG=$RCS_LOCALE; "
    'echo "[+] Locale remoto: $RCS_LOCALE"; '
)


def _envolver_locale_remoto(conexion) -> None:
    """Fuerza un locale UTF-8 en cada comando remoto.

    ``eventquery2`` escribe el CSV con la codificación por defecto de Python.
    Si el shell remoto arranca en ASCII, un nombre con acento rompe la descarga
    con ``UnicodeEncodeError``. El prefijo elige un locale UTF-8 válido en el
    servidor antes de ejecutar el comando original.
    """
    original = getattr(conexion, "ssh_login", None)
    if original is None:
        return

    def ssh_login(comando):
        return original(PREFIJO_LOCALE_REMOTO + comando)

    conexion.ssh_login = ssh_login


def _archivo(request: CatalogRequest, kind: str) -> CatalogRequestFile:
    for archivo in request.files:
        if archivo.kind == kind:
            return archivo
    archivo = CatalogRequestFile(
        kind=kind,
        format=kind,
        status="pending",
    )
    request.files.append(archivo)
    return archivo


def _tiene(request: CatalogRequest, kind: str) -> bool:
    return any(archivo.kind == kind for archivo in request.files)


def _actualizar(request: CatalogRequest, **campos) -> None:
    for clave, valor in campos.items():
        setattr(request, clave, valor)
    db.session.commit()


def _progreso(request: CatalogRequest, base: int, ancho: int, fraccion: float) -> None:
    valor = int(base + ancho * max(0.0, min(1.0, fraccion)))
    if valor > (request.progress or 0):
        request.progress = min(99, valor)
        db.session.commit()


def _guardar_archivo(
    request: CatalogRequest,
    kind: str,
    origen: Path,
    workspace: Path,
) -> Path:
    archivo = _archivo(request, kind)
    archivo.status = "ok"
    archivo.original_name = origen.name
    destino = workspace / "files" / ("select.out" if kind == "seisan" else origen.name)
    if origen.resolve() != destino.resolve():
        shutil.copy2(origen, destino)
    archivo.stored_path = str(destino.relative_to(workspace))
    archivo.size = destino.stat().st_size
    archivo.sha256 = _sha256(destino)
    db.session.commit()
    return destino


def _crear_job(request: CatalogRequest, workspace: Path) -> Job:
    locales = [
        archivo
        for archivo in request.files
        if archivo.kind in ("seisan", "seiscomp") and archivo.status == "ok" and archivo.stored_path
    ]
    if not locales:
        raise RuntimeError("La solicitud no tiene ninguna fuente local válida.")

    principal = request.primary_source
    if principal not in {archivo.kind for archivo in locales}:
        principal = (
            "seiscomp"
            if any(archivo.kind == "seiscomp" for archivo in locales)
            else locales[0].kind
        )
    locales.sort(key=lambda archivo: (0 if archivo.kind == principal else 1, archivo.kind))

    job = Job(
        id=nuevo_uuid(),
        period_start=request.period_start,
        period_end=request.period_end,
        status="queued",
        origin="ssh",
        catalog_request_id=request.id,
        current_step="En cola",
        created_by_id=request.requested_by_id,
    )
    db.session.add(job)
    db.session.commit()
    job_workspace = crear_workspace(job.id)

    db.session.add(
        JobSource(
            job_id=job.id,
            kind="eventquery",
            alias="Eventquery",
            format="eventquery",
            role="referencia",
            priority=0,
            capabilities=sorted(fuente("eventquery").capacidades),
        )
    )
    for indice, archivo in enumerate(locales, start=1):
        formato = archivo.format or archivo.kind
        alias = "SeisComp (exportación)" if archivo.kind == "seiscomp" else "Seisan (descarga SSH)"
        db.session.add(
            JobSource(
                job_id=job.id,
                kind=archivo.kind,
                alias=alias,
                format=formato,
                role=("local_principal" if archivo.kind == principal else "local_secundaria"),
                priority=indice,
                capabilities=sorted(fuente(formato).capacidades),
            )
        )

    for archivo in request.files:
        if archivo.status != "ok" or not archivo.stored_path:
            continue
        origen = workspace / archivo.stored_path
        if not origen.is_file():
            continue
        almacenado = f"{archivo.kind}__{origen.name}"
        destino = job_workspace / "inputs" / almacenado
        shutil.copy2(origen, destino)
        db.session.add(
            JobFile(
                job_id=job.id,
                kind=archivo.kind,
                original_name=archivo.original_name or origen.name,
                stored_name=f"inputs/{almacenado}",
                size=destino.stat().st_size,
                sha256=_sha256(destino),
            )
        )
    db.session.commit()

    registrar(
        "job.create",
        entity=job.id,
        meta={
            "origen": "ssh",
            "solicitud": request.id,
            "inicio": job.inicio14,
            "fin": job.fin14,
            "fuentes": [archivo.kind for archivo in locales],
            "principal": principal,
        },
        user_id=request.requested_by_id,
    )
    try:
        encolar_trabajo(job.id)
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.error = f"No se pudo encolar el trabajo: {exc}"
        job.current_step = "Error al encolar"
        db.session.commit()
        raise
    return job


def ejecutar_solicitud(request_id: str, password: str) -> dict:
    """Descarga los catálogos, valida y crea el trabajo."""
    request = db.session.get(CatalogRequest, request_id)
    if request is None:
        return {"solicitud": request_id, "estado": "inexistente"}
    if request.status in ("done", "cancelled"):
        return {"solicitud": request_id, "estado": request.status}

    workspace = preparar_workspace(request.id)
    log = _Log(workspace / "logs" / "fetch.log")
    request.status = "running"
    request.progress = 1
    request.current_step = "Conectando al servidor"
    request.started_at = datetime.now(UTC)
    request.error = None
    db.session.commit()

    for archivo in request.files:
        archivo.status = "pending"
    db.session.commit()

    try:
        tc = _cargar_traer_catalogos()
        tc.IP_REMOTA = request.server or tc.IP_REMOTA
        tc.USUARIO_REMOTO = request.remote_user or tc.USUARIO_REMOTO
        log.escribir(f"Solicitud {request.id} · {request.inicio14} → {request.fin14}")
        log.escribir(f"Servidor: {tc.USUARIO_REMOTO}@{tc.IP_REMOTA}")

        with tc.Conexion(password, log=log.escribir) as conexion:
            _envolver_locale_remoto(conexion)
            tc.verificar_conexion(
                conexion,
                log=log.escribir,
                progreso=lambda f: _progreso(request, 5, 5, f),
            )

            archivo = _archivo(request, "eventquery")
            archivo.status = "downloading"
            request.current_step = "Descargando eventquery"
            db.session.commit()

            def progreso_eventquery(f):
                _progreso(request, 10, 30, f)

            ruta_eventquery = tc.traer_eventquery(
                request.inicio14,
                request.fin14,
                conexion,
                cwd=str(workspace),
                log=log.escribir,
                progreso=progreso_eventquery,
                forzar=True,
            )
            _guardar_archivo(request, "eventquery", Path(ruta_eventquery), workspace)

            if _tiene(request, "seisan"):
                archivo = _archivo(request, "seisan")
                archivo.status = "downloading"
                request.current_step = "Descargando Seisan"
                db.session.commit()

                def progreso_seisan(f):
                    _progreso(request, 40, 25, f)

                ruta_seisan = tc.traer_seisan(
                    request.inicio14,
                    request.fin14,
                    conexion,
                    cwd=str(workspace),
                    log=log.escribir,
                    progreso=progreso_seisan,
                    forzar=True,
                )
                _guardar_archivo(request, "seisan", Path(ruta_seisan), workspace)

            if _tiene(request, "seiscomp"):
                from .seiscomp import exportar_ventana

                archivo = _archivo(request, "seiscomp")
                archivo.status = "downloading"
                request.current_step = "Exportando SeisComp (todas las bases)"
                db.session.commit()
                salida = workspace / "files" / f"seiscomp_{request.inicio14}_{request.fin14}.csv"
                exportar_ventana(
                    request.inicio14,
                    request.fin14,
                    salida,
                    log=log.escribir,
                    progreso=lambda f: _progreso(request, 65, 25, f),
                )
                _guardar_archivo(request, "seiscomp", salida, workspace)

        request.current_step = "Validando catálogos"
        request.progress = 95
        db.session.commit()

        validaciones = {}
        for archivo in request.files:
            if not archivo.stored_path:
                continue
            resultado = validar_fuente(
                archivo.format or archivo.kind,
                workspace / archivo.stored_path,
                request.period_start,
                request.period_end,
            )
            validaciones[archivo.kind] = resultado
            archivo.status = "ok" if resultado["ok"] else "error"
            archivo.message = "\n".join(resultado["errores"] + resultado["advertencias"]) or None
        db.session.commit()

        if not all(resultado["ok"] for resultado in validaciones.values()):
            errores = [
                f"{codigo}: {'; '.join(resultado['errores'])}"
                for codigo, resultado in validaciones.items()
                if resultado["errores"]
            ]
            request.status = "failed"
            request.current_step = "Validación fallida"
            request.error = " | ".join(errores) or "Algún catálogo no validó."
            request.finished_at = datetime.now(UTC)
            db.session.commit()
            log.escribir("ERROR: " + request.error)
            return {"solicitud": request.id, "estado": "failed"}

        job = _crear_job(request, workspace)
        request.status = "done"
        request.progress = 100
        request.current_step = "Trabajo creado"
        request.finished_at = datetime.now(UTC)
        db.session.commit()
        log.escribir(f"[OK] Trabajo creado: {job.id}")
        return {"solicitud": request.id, "estado": "done", "job": job.id}

    except Exception as exc:  # noqa: BLE001 - se informa en la solicitud
        log.escribir(f"ERROR: {exc}")
        request.status = "failed"
        request.current_step = "Error de descarga"
        request.error = str(exc)
        request.finished_at = datetime.now(UTC)
        for archivo in request.files:
            if archivo.status in ("pending", "downloading"):
                archivo.status = "error"
                archivo.message = str(exc)
        db.session.commit()
        return {"solicitud": request.id, "estado": "failed", "error": str(exc)}


def reintentar_solicitud(request_id: str, password: str) -> dict:
    request = db.session.get(CatalogRequest, request_id)
    if request is None:
        return {"solicitud": request_id, "estado": "inexistente"}
    if request.status == "running":
        return {"solicitud": request_id, "estado": "running"}
    request.status = "queued"
    request.progress = 0
    request.current_step = "Reintentando"
    request.error = None
    request.finished_at = None
    for archivo in request.files:
        archivo.status = "pending"
        archivo.message = None
    db.session.commit()
    return {"solicitud": request_id, "estado": "queued"}
