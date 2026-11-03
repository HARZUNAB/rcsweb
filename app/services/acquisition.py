"""Adquisición de catálogos por SSH/SCP y creación del trabajo."""

from __future__ import annotations

import hashlib
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from flask import current_app

from ..domain.catalogs import manifest as fuentes_manifest
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
from .validators import validar_fuente
from .workspace import crear_workspace

SUBDIRECTORIOS = ("files", "logs", "trabajo", "inputs")


class _Log:
    def __init__(self, ruta: Path):
        self.ruta = ruta
        ruta.parent.mkdir(parents=True, exist_ok=True)
        self.ruta.write_text("", encoding="utf-8")

    def escribir(self, texto: str) -> None:
        linea = str(texto).rstrip("\n")
        current_app.logger.info("fetch %s: %s", self.ruta.parent.parent.name, linea)
        if linea.startswith("$ ssh") or linea.startswith("$ scp") or "Permanently added" in linea:
            return
        with self.ruta.open("a", encoding="utf-8") as archivo:
            archivo.write(linea + "\n")


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
    lineas = [
        linea
        for linea in lineas
        if not linea.startswith("$ ssh")
        and not linea.startswith("$ scp")
        and "Permanently added" not in linea
    ]
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


def _mensaje_error(exc: Exception) -> str:
    texto = str(exc).strip()
    return texto.replace(
        "La conexión SSH falló. Revise el registro.",
        "No se pudo conectar con el servidor. Revise el registro.",
    )


def _actualizar(request: CatalogRequest, **campos) -> None:
    for clave, valor in campos.items():
        setattr(request, clave, valor)
    db.session.commit()


def _progreso(request: CatalogRequest, base: int, ancho: int, fraccion: float) -> None:
    valor = int(base + ancho * max(0.0, min(1.0, fraccion)))
    if valor > (request.progress or 0):
        request.progress = min(99, valor)
        db.session.commit()


def _recalcular_progreso(request: CatalogRequest) -> None:
    archivos = [archivo for archivo in request.files if archivo.progress is not None]
    if not archivos:
        return
    total = sum(max(0, min(100, archivo.progress or 0)) for archivo in archivos)
    request.progress = max(
        request.progress or 0,
        min(95, int(total / len(archivos))),
    )
    db.session.commit()


def _progreso_archivo(
    request: CatalogRequest, archivo: CatalogRequestFile, fraccion: float
) -> None:
    try:
        valor = int(max(0.0, min(1.0, float(fraccion))) * 100)
    except (TypeError, ValueError):
        return
    archivo.progress = max(archivo.progress or 0, valor)
    _recalcular_progreso(request)


def _guardar_archivo(
    request: CatalogRequest,
    kind: str,
    origen: Path,
    workspace: Path,
) -> Path:
    archivo = _archivo(request, kind)
    definicion = fuentes_manifest.por_id(kind)
    archivo.status = "ok"
    archivo.original_name = origen.name
    nombre = definicion.stored_filename if definicion else ""
    destino = workspace / "files" / (nombre or origen.name)
    if origen.resolve() != destino.resolve():
        shutil.copy2(origen, destino)
    archivo.stored_path = str(destino.relative_to(workspace))
    archivo.size = destino.stat().st_size
    archivo.sha256 = _sha256(destino)
    db.session.commit()
    return destino


def _crear_job(request: CatalogRequest, workspace: Path) -> Job:
    referencia = fuentes_manifest.referencia()
    locales = [
        archivo
        for archivo in request.files
        if archivo.kind != referencia.id
        and archivo.status == "ok"
        and archivo.stored_path
    ]
    if not locales:
        raise RuntimeError("La solicitud no tiene ninguna fuente local válida.")

    principal = request.primary_source
    if principal not in {archivo.kind for archivo in locales}:
        predeterminada = fuentes_manifest.default_primary()
        principal = (
            predeterminada
            if predeterminada in {archivo.kind for archivo in locales}
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
        station_radius_km=request.station_radius_km,
        created_by_id=request.requested_by_id,
    )
    request.job_deleted_at = None
    db.session.add(job)
    db.session.commit()
    job_workspace = crear_workspace(job.id)

    db.session.add(
        JobSource(
            job_id=job.id,
            kind=referencia.id,
            alias=referencia.label,
            format=referencia.format,
            role="referencia",
            priority=0,
            capabilities=sorted(referencia.capacidades),
        )
    )
    for indice, archivo in enumerate(locales, start=1):
        definicion = fuentes_manifest.por_id(archivo.kind)
        formato = archivo.format or (definicion.format if definicion else archivo.kind)
        alias = archivo.display_name or (
            definicion.label if definicion else archivo.kind
        )
        db.session.add(
            JobSource(
                job_id=job.id,
                kind=archivo.kind,
                alias=alias,
                format=formato,
                role=("local_principal" if archivo.kind == principal else "local_secundaria"),
                priority=indice,
                capabilities=sorted(
                    definicion.capacidades if definicion else frozenset()
                ),
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
            "radio_km": request.station_radius_km,
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
        archivo.progress = 0
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

            referencia = fuentes_manifest.referencia()
            archivos = sorted(
                request.files,
                key=lambda archivo: 0 if archivo.kind == referencia.id else 1,
            )
            for archivo in archivos:
                definicion = fuentes_manifest.por_id(archivo.kind)
                if definicion is None or not definicion.descargable:
                    continue
                archivo.status = "downloading"
                request.current_step = f"Descargando {definicion.label}"
                db.session.commit()
                manejador = definicion.download_handler

                if manejador == "eventquery":
                    ruta = tc.traer_eventquery(
                        request.inicio14,
                        request.fin14,
                        conexion,
                        cwd=str(workspace),
                        log=log.escribir,
                        progreso=lambda f, archivo=archivo: _progreso_archivo(
                            request, archivo, f
                        ),
                        forzar=True,
                    )
                elif manejador == "seisan":
                    ruta = tc.traer_seisan(
                        request.inicio14,
                        request.fin14,
                        conexion,
                        cwd=str(workspace),
                        log=log.escribir,
                        progreso=lambda f, archivo=archivo: _progreso_archivo(
                            request, archivo, f
                        ),
                        forzar=True,
                    )
                elif manejador == "seiscomp":
                    from .seiscomp import exportar_ventana

                    salida = (
                        workspace
                        / "files"
                        / f"{definicion.id}_{request.inicio14}_{request.fin14}.csv"
                    )
                    exportar_ventana(
                        request.inicio14,
                        request.fin14,
                        salida,
                        radio_km=request.station_radius_km or 400,
                        log=log.escribir,
                        log_detalle=current_app.logger.info,
                        progreso=lambda f, archivo=archivo: _progreso_archivo(
                            request, archivo, f
                        ),
                    )
                    ruta = salida
                else:
                    raise RuntimeError(
                        f"No hay manejador de descarga para {definicion.label}."
                    )

                _guardar_archivo(request, archivo.kind, Path(ruta), workspace)
                archivo.progress = 100
                _recalcular_progreso(request)

        request.current_step = "Validando catálogos"
        request.progress = 95
        db.session.commit()

        validaciones = {}
        for archivo in request.files:
            if not archivo.stored_path:
                continue
            definicion = fuentes_manifest.por_id(archivo.kind)
            validador = (
                definicion.validator
                if definicion
                else (archivo.format or archivo.kind)
            )
            resultado = validar_fuente(
                validador,
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
        mensaje = _mensaje_error(exc)
        log.escribir(f"ERROR: {mensaje}")
        request.status = "failed"
        request.current_step = "Error de descarga"
        request.error = mensaje
        request.finished_at = datetime.now(UTC)
        for archivo in request.files:
            if archivo.status in ("pending", "downloading"):
                archivo.status = "error"
                archivo.message = mensaje
        db.session.commit()
        return {"solicitud": request.id, "estado": "failed", "error": mensaje}


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
        archivo.progress = 0
        archivo.message = None
    db.session.commit()
    return {"solicitud": request_id, "estado": "queued"}
