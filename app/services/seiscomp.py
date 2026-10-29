"""Exportación de SeisComp en solo lectura.

Reutiliza ``exporta_ventana_seiscomp.py`` del core, que combina todas las bases
del servidor. La conexión se hace con un rol de solo lectura y las credenciales
se toman de variables de entorno; nunca se guardan en la base.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from flask import current_app

VARIABLES = (
    "SEISCOMP_DB_HOST",
    "SEISCOMP_DB_USER",
    "SEISCOMP_DB_PASSWORD",
)


def configurada() -> bool:
    return all(os.environ.get(nombre) for nombre in VARIABLES)


def _config() -> dict:
    return {
        "host": os.environ.get("SEISCOMP_DB_HOST", ""),
        "port": os.environ.get("SEISCOMP_DB_PORT", "5432"),
        "database": os.environ.get("SEISCOMP_DB_NAME", "seiscomp2"),
        "user": os.environ.get("SEISCOMP_DB_USER", ""),
        "password": os.environ.get("SEISCOMP_DB_PASSWORD", ""),
    }


def _entorno() -> dict:
    config = _config()
    entorno = os.environ.copy()
    entorno.update(
        {
            "RCS_DB_HOST": config["host"],
            "RCS_DB_DATABASE": config["database"],
            "RCS_DB_USER": config["user"],
            "RCS_DB_PASSWORD": config["password"],
            "PGPORT": config["port"],
            "PYTHONUNBUFFERED": "1",
        }
    )
    return entorno


def probar_conexion() -> dict:
    """SELECT 1 + listado de bases, sin escribir nada."""
    if not configurada():
        return {
            "ok": False,
            "error": "Faltan SEISCOMP_DB_HOST/USER/PASSWORD en el entorno.",
            "bases": [],
        }
    config = _config()
    try:
        import psycopg2

        conexion = psycopg2.connect(
            host=config["host"],
            port=int(config["port"]),
            dbname=config["database"],
            user=config["user"],
            password=config["password"],
            connect_timeout=8,
            options=("-c default_transaction_read_only=on -c statement_timeout=15000"),
        )
        try:
            cursor = conexion.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.execute(
                "SELECT datname FROM pg_database "
                "WHERE datistemplate = false AND datallowconn "
                "AND datname NOT IN ('postgres','template0','template1') "
                "ORDER BY datname"
            )
            bases = [fila[0] for fila in cursor.fetchall()]
        finally:
            conexion.close()
        return {"ok": True, "error": None, "bases": bases}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "bases": []}


def exportar_ventana(
    inicio14: str,
    fin14: str,
    salida: Path,
    *,
    radio_km: int = 400,
    log=None,
    log_detalle=None,
    progreso=None,
    timeout: int = 3600,
) -> Path:
    """Exporta la ventana combinando todas las bases de SeisComp."""
    log = log or (lambda _t: None)
    log_detalle = log_detalle or (lambda texto: current_app.logger.info("seiscomp: %s", texto))
    if not configurada():
        raise RuntimeError("SeisComp no está configurado.")
    if radio_km <= 0:
        raise RuntimeError("El radio de estaciones debe ser mayor que cero.")

    core = Path(current_app.config["RCS_CORE_PATH"])
    script = core / "exporta_ventana_seiscomp.py"
    if not script.is_file():
        raise RuntimeError("No se encontró exporta_ventana_seiscomp.py en el core.")
    runner = Path(__file__).with_name("runner_seiscomp.py")
    if not runner.is_file():
        raise RuntimeError("No se encontró el runner de SeisComp.")

    salida.parent.mkdir(parents=True, exist_ok=True)
    if progreso:
        progreso(0.05)
    comando = [
        sys.executable,
        str(runner),
        str(script),
        inicio14,
        fin14,
        str(salida),
        "--base",
        "todas",
        "--radio-km",
        str(radio_km),
    ]
    log("Exportando datos de SeisComp…")
    log_detalle("$ " + " ".join(comando[:3]) + f" … --base todas --radio-km {radio_km}")
    proceso = subprocess.run(
        comando,
        cwd=str(salida.parent.parent),
        env=_entorno(),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    for linea in (proceso.stdout or "").splitlines():
        log_detalle(linea)
    for linea in (proceso.stderr or "").splitlines():
        log_detalle(linea)
    if proceso.returncode != 0:
        raise RuntimeError(
            f"No se pudieron obtener los datos de SeisComp (código {proceso.returncode}). Revisá el log."
        )
    marca = Path(str(salida) + ".completo")
    if not salida.is_file() or not marca.is_file():
        raise RuntimeError("SeisComp no dejó el catálogo o la marca de fin.")
    log("Datos de SeisComp obtenidos.")
    if progreso:
        progreso(1.0)
    return salida
