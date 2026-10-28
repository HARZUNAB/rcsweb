"""Endpoint de salud y diagnóstico del entorno."""

from __future__ import annotations

import os
from pathlib import Path

from flask import Blueprint, current_app, jsonify
from sqlalchemy import text

from ..extensions import db

health_bp = Blueprint("health", __name__)


def _escribible(ruta: Path) -> bool:
    try:
        ruta.mkdir(parents=True, exist_ok=True)
        prueba = ruta / ".escritura"
        prueba.write_text("ok", encoding="utf-8")
        prueba.unlink()
        return True
    except OSError:
        return False


@health_bp.get("/health")
def health():
    base_ok = True
    detalle_base = "ok"
    try:
        db.session.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - depende del entorno
        base_ok = False
        detalle_base = type(exc).__name__

    core = Path(current_app.config["RCS_CORE_PATH"])
    workspace = Path(current_app.config["WORKSPACE_ROOT"])
    dump = Path(
        os.environ.get(
            "CSN_DUMP_PATH",
            "/data/csn/dumps/csn_test_full_2026-09-30.dump",
        )
    )

    cuerpo = {
        "status": "ok" if base_ok else "degraded",
        "version": current_app.config["APP_VERSION"],
        "database": detalle_base,
        "core_montado": core.is_dir(),
        "workspace_escribible": _escribible(workspace),
        "dump_presente": dump.is_file(),
    }
    return jsonify(cuerpo), (200 if base_ok else 503)
