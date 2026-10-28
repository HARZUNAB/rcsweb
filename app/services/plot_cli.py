"""Renderizador de mapas en subproceso.

Se ejecuta con ``cwd`` en el workspace del trabajo, backend Agg y el core en
``sys.path``. Recibe por stdin un JSON con ``eventos`` y ``fuente``, y escribe
el PNG en el argumento 1.
"""

from __future__ import annotations

import json
import os
import sys

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

CORE = os.environ.get("RCS_CORE_PATH", "/opt/rcs-core")
if CORE not in sys.path:
    sys.path.insert(0, CORE)

CARTOPY_DATA = os.environ.get("CARTOPY_DATA_DIR")
if CARTOPY_DATA:
    import cartopy  # noqa: E402

    cartopy.config["data_dir"] = CARTOPY_DATA

# Cartopy 0.24 + shapely 2.2 falla al dibujar la grilla con un LinearRing no
# cerrado. La grilla es cosmética: se desactiva para poder renderizar.
import cartopy.mpl.gridliner as gridliner  # noqa: E402

gridliner.Gridliner._draw_gridliner = lambda self, renderer=None: None

import plotear  # noqa: E402

plotear._mostrar_figura = lambda bloquear: None


def main() -> int:
    if len(sys.argv) < 2:
        print("uso: plot_cli.py <salida.png>", file=sys.stderr)
        return 2
    datos = json.load(sys.stdin)
    plotear.abrir_eventos(datos["eventos"], datos["fuente"])
    figura = plt.gcf()
    figura.savefig(sys.argv[1], dpi=110, bbox_inches="tight")
    plt.close("all")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
