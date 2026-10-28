#!/usr/bin/env python3
"""Ejecuta una exportación de SeisComp forzando conexiones de solo lectura.

El script del core abre las conexiones con ``psycopg2.connect(...,
options="-c statement_timeout=...")``. Ese parámetro pisa ``PGOPTIONS``, así que
la única garantía de solo lectura que queda del lado del proceso es envolver
``psycopg2.connect``. El rol de base también debe ser de solo lectura; esto es
una segunda barrera.

Uso:
    python runner_seiscomp.py <script.py> [argumentos...]
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def forzar_solo_lectura() -> None:
    try:
        import psycopg2
    except ImportError:  # pragma: no cover - la imagen siempre lo instala
        return

    original = psycopg2.connect

    def connect(*args, **kwargs):
        opciones = kwargs.get("options") or ""
        if "default_transaction_read_only" not in opciones:
            kwargs["options"] = f"{opciones} -c default_transaction_read_only=on".strip()
        return original(*args, **kwargs)

    psycopg2.connect = connect


def main() -> int:
    if len(sys.argv) < 2:
        print("Uso: runner_seiscomp.py <script.py> [argumentos...]", file=sys.stderr)
        return 2
    script = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(script.parent))
    sys.argv = sys.argv[1:]
    forzar_solo_lectura()
    runpy.run_path(str(script), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
