"""Preparación y limpieza del workspace de cada trabajo.

El pipeline del proyecto base resuelve todas sus rutas relativas contra el
directorio de ejecución (``rutas.py``). Por eso cada trabajo vive en su propio
directorio y los scripts se ejecutan con ``cwd`` ahí dentro.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from flask import current_app
from werkzeug.utils import secure_filename

from ..models import Job

SUBDIRECTORIOS = (
    "inputs",
    "datos",
    "informes",
    "analistas",
    "trabajo",
    "ploteo",
    "descargas",
    "resultados",
    "plots",
    "logs",
)

# Insumos del proyecto base que el pipeline lee desde el CWD. Se enlazan en
# solo lectura; no se copian (hay archivos de cientos de MB).
INSUMOS = (
    "grillas",
    "plantillas",
    "base_2020_2026.dat",
    "base_2020_2026.csv",
    "localidades.csv",
    "NE2_LR_LC_SR_W_DR.tif",
    "relieve_chile.tif",
)

NOMBRES_CANONICOS = {
    "seisan": "select.out",
    "eventquery": "eventquery_{inicio}_{fin}.csv",
    "seiscomp": "seiscomp_{inicio}_{fin}.csv",
}


def ruta_workspace(job_id: str) -> Path:
    raiz = Path(current_app.config["WORKSPACE_ROOT"]).resolve()
    return raiz / str(job_id)


def crear_workspace(job_id: str) -> Path:
    workspace = ruta_workspace(job_id)
    for nombre in SUBDIRECTORIOS:
        (workspace / nombre).mkdir(parents=True, exist_ok=True)
    return workspace


def nombre_canonico(kind: str, inicio14: str, fin14: str) -> str:
    return NOMBRES_CANONICOS[kind].format(inicio=inicio14, fin=fin14)


def nombre_entrada(kind: str, nombre_original: str) -> str:
    """Nombre seguro dentro de ``inputs/``, con el tipo como prefijo."""
    limpio = secure_filename(nombre_original) or "archivo"
    return f"{kind}__{limpio}"


def guardar_archivo(file_storage, destino: Path) -> tuple[int, str]:
    """Guarda el upload en streaming y devuelve (tamaño, sha256)."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    tamano = 0
    with destino.open("wb") as salida:
        while True:
            bloque = file_storage.stream.read(1024 * 1024)
            if not bloque:
                break
            salida.write(bloque)
            digest.update(bloque)
            tamano += len(bloque)
    return tamano, digest.hexdigest()


def enlazar_insumos(workspace: Path) -> None:
    """Crea symlinks a los insumos del core montado en solo lectura."""
    core = Path(current_app.config["RCS_CORE_PATH"])
    for nombre in INSUMOS:
        origen = core / nombre
        destino = workspace / nombre
        if not origen.exists() or destino.exists():
            continue
        try:
            destino.symlink_to(origen)
        except OSError:
            # Sin permiso o sin symlinks: se sigue; los pasos que lo necesiten
            # fallarán con un mensaje claro.
            continue


def preparar_entradas(job: Job) -> Path:
    """Copia los uploads a los nombres canónicos y enlaza los insumos."""
    workspace = crear_workspace(job.id)
    for archivo in job.files:
        destino = workspace / archivo.stored_name
        if not destino.is_file():
            continue
        canonico = nombre_canonico(archivo.kind, job.inicio14, job.fin14)
        objetivo = workspace / canonico
        if not objetivo.exists():
            shutil.copy2(destino, objetivo)
    enlazar_insumos(workspace)
    return workspace


def ruta_log(workspace: Path) -> Path:
    return workspace / "logs" / "pipeline.log"


def leer_log(workspace: Path, max_lineas: int = 200) -> list[str]:
    ruta = ruta_log(workspace)
    if not ruta.is_file():
        return []
    try:
        with ruta.open(encoding="utf-8", errors="replace") as archivo:
            lineas = archivo.readlines()
    except OSError:
        return []
    return [linea.rstrip("\n") for linea in lineas[-max_lineas:]]
