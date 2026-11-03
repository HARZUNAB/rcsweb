"""Renderizador de mapas en subproceso.

Se ejecuta con ``cwd`` en el workspace del trabajo, backend Agg y el core en
``sys.path``. Recibe por stdin un JSON con ``eventos`` y ``fuente``, y escribe
el PNG en el argumento 1.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

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

# El subproceso corre con cwd en el workspace y no debe depender de que el
# paquete ``app`` esté instalado o resuelto en sys.path. Se carga el módulo
# hermano directamente por ruta.
_ruta_extent = Path(__file__).with_name("extent.py")
_spec_extent = importlib.util.spec_from_file_location("rcs_extent", _ruta_extent)
if _spec_extent is None or _spec_extent.loader is None:
    raise ImportError(f"No se pudo cargar {_ruta_extent}")
_modulo_extent = importlib.util.module_from_spec(_spec_extent)
_spec_extent.loader.exec_module(_modulo_extent)
margen_planta_eventos = _modulo_extent.margen_planta_eventos
extender_extent = getattr(_modulo_extent, "extender_extent", None)

plotear._mostrar_figura = lambda bloquear: None

# Ajuste de contexto de la planta sin modificar el proyecto base: un evento
# solo se muestra con vista regional; varias soluciones cercanas se acercan
# para poder diferenciarlas.
_extent_original = plotear._extent_planta_por_eventos
_contexto: tuple[float, float] | None = None


def _extent_con_contexto(
    eventos,
    perfil=None,
    territorio=None,
    margen_adicional=None,
):
    margen = margen_planta_eventos(eventos)
    if margen is not None:
        margen_adicional = margen
    extent = _extent_original(eventos, perfil, territorio, margen_adicional)
    if _contexto is not None and extent is not None and extender_extent is not None:
        extent = extender_extent(extent, _contexto, aspecto_maximo=2.0)
    return extent


plotear._extent_planta_por_eventos = _extent_con_contexto


def _quitar_leyendas(figura) -> None:
    for eje in figura.axes:
        leyenda_eje = eje.get_legend()
        if leyenda_eje is not None:
            leyenda_eje.remove()
    for leyenda_figura in list(figura.legends):
        leyenda_figura.remove()


def _leyenda_catalogo(figura, items: list[dict], modo: str) -> None:
    handles = [
        Line2D(
            [0],
            [0],
            marker="o",
            color="w",
            markerfacecolor=item.get("color", "#ffff00"),
            markeredgecolor="black",
            markeredgewidth=1.0,
            markersize=8,
            label=item.get("etiqueta", ""),
        )
        for item in items
        if item.get("etiqueta")
    ]
    if not handles:
        return
    if modo == "perfil" and figura.axes:
        figura.axes[-1].legend(
            handles=handles,
            loc="lower right",
            fontsize=7,
            framealpha=0.9,
            ncol=1,
        )
        return
    figura.legend(
        handles=handles,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.01),
        ncol=len(handles),
        fontsize=8,
        frameon=False,
    )


def main() -> int:
    if len(sys.argv) < 2:
        print("uso: plot_cli.py <salida.png>", file=sys.stderr)
        return 2
    datos = json.load(sys.stdin)
    global _contexto
    contexto = datos.get("contexto")
    if contexto:
        _contexto = (float(contexto[0]), float(contexto[1]))
    modo = datos.get("modo")
    fuente = datos.get("fuente", "")
    etiqueta_fuente = datos.get("etiqueta_fuente") or fuente
    if fuente:
        plotear._ETIQUETA_FUENTE[fuente] = etiqueta_fuente
    if not datos.get("sospechosos", True):
        # Los mapas de catálogo solo distinguen percibidos y no percibidos.
        try:
            import sismicidad  # type: ignore

            sismicidad.es_sospechoso = lambda _evento: False
        except Exception:
            pass
    if modo == "planta":
        plotear.plotear_planta(
            datos["eventos"],
            fuente,
            territorio=datos.get("territorio"),
            mostrar_json=False,
            con_boton_detener=False,
            bloquear=False,
            delta_auto=False,
        )
    else:
        plotear.abrir_eventos(datos["eventos"], fuente)
    figura = plt.gcf()
    items = datos.get("leyenda_items")
    if items is not None:
        _quitar_leyendas(figura)
        _leyenda_catalogo(figura, items, modo)
    elif not datos.get("leyenda", True):
        _quitar_leyendas(figura)
    if modo == "perfil" and figura.axes:
        perfil = figura.axes[-1]
        bbox = perfil.get_window_extent().transformed(
            figura.dpi_scale_trans.inverted()
        )
        figura.savefig(sys.argv[1], dpi=110, bbox_inches=bbox)
    else:
        figura.savefig(sys.argv[1], dpi=110, bbox_inches="tight")
    plt.close("all")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
