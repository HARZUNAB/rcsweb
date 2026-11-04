"""Renderizador de mapas en subproceso.

Se ejecuta con ``cwd`` en el workspace del trabajo, backend Agg y el core en
``sys.path``. Recibe por stdin un JSON con ``eventos`` y ``fuente``, y escribe
el PNG en el argumento 1.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.transforms import Bbox  # noqa: E402

CORE = os.environ.get("RCS_CORE_PATH") or str(
    Path(__file__).resolve().parents[2] / "core"
)
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

# Ajuste de contexto de la planta sin modificar el core: un evento
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


def _quitar_sospechosos(figura) -> None:
    """Quita «0 sospechosos» de los textos del resumen en mapas de catálogo."""
    patron = re.compile(r"\s*[·\-]?\s*0\s+sospechosos?", re.IGNORECASE)
    textos = list(figura.texts)
    for eje in figura.axes:
        textos.extend(eje.texts)
    for texto in textos:
        actual = texto.get_text()
        if "sospechos" not in actual.lower():
            continue
        nuevo = re.sub(r"\s{2,}", " ", patron.sub("", actual)).strip(" ·")
        texto.set_text(nuevo)
        if not nuevo:
            texto.set_visible(False)


def _es_punto_localidad(linea) -> bool:
    """True para el punto negro que dibuja el core por cada localidad."""
    try:
        xdata, ydata = linea.get_data()
        return (
            str(linea.get_marker()).lower() in ("o", "circle")
            and linea.get_markersize() <= 4
            and len(xdata) == 1
            and len(ydata) == 1
        )
    except Exception:
        return False


def _ajustar_localidades(figura, modo: str, eventos=None) -> None:
    """Deja solo la localidad más cercana al sismo y oculta el resto.

    El mapa de Otros incluye la costa chilena como referencia. Para no llenar
    la imagen de nombres y puntos, se conserva únicamente la localidad más
    cercana a los eventos ploteados.
    """
    if modo == "perfil" or not figura.axes:
        return
    ax = figura.axes[0]
    textos = [texto for texto in ax.texts if texto.get_text().strip()]
    if not textos:
        return
    xmin, xmax = ax.get_xlim()
    ymin, ymax = ax.get_ylim()
    ancho = xmax - xmin
    alto = ymax - ymin

    referencias = []
    for evento in eventos or []:
        try:
            referencias.append(
                (float(evento["longitud"]), float(evento["latitud"]))
            )
        except (KeyError, TypeError, ValueError):
            continue
    if not referencias:
        if _contexto is not None:
            ref_lat, ref_lon = _contexto
            referencias = [(ref_lon, ref_lat)]
        else:
            referencias = [((xmin + xmax) / 2, (ymin + ymax) / 2)]

    def _distancia(texto) -> float:
        x, y = texto.get_position()
        return min((x - lon) ** 2 + (y - lat) ** 2 for lon, lat in referencias)

    cercano = min(textos, key=_distancia)
    for texto in textos:
        if texto is not cercano:
            texto.set_visible(False)

    origen = cercano.get_position()
    puntos = [linea for linea in ax.lines if _es_punto_localidad(linea)]
    if puntos:
        def _distancia_punto(linea) -> float:
            xdata, ydata = linea.get_data()
            return (float(xdata[0]) - origen[0]) ** 2 + (
                float(ydata[0]) - origen[1]
            ) ** 2

        punto = min(puntos, key=_distancia_punto)
        for linea in puntos:
            if linea is not punto:
                linea.set_visible(False)

    x, y = cercano.get_position()
    if x > xmax - ancho * 0.12:
        cercano.set_ha("right")
        x = xmax - ancho * 0.02
    elif x < xmin + ancho * 0.12:
        cercano.set_ha("left")
        x = xmin + ancho * 0.02
    if y > ymax - alto * 0.08:
        cercano.set_va("top")
        y = ymax - alto * 0.02
    elif y < ymin + alto * 0.08:
        cercano.set_va("bottom")
        y = ymin + alto * 0.02
    cercano.set_position((x, y))
    cercano.set_fontsize(8)
    cercano.set_clip_on(True)

def _leyenda_catalogo(figura, items: list[dict], modo: str):
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
        return None
    if modo == "perfil" and figura.axes:
        perfil = figura.axes[-1]
        posicion = perfil.get_position()
        centro = posicion.x0 + posicion.width / 2
        return figura.legend(
            handles=handles,
            loc="lower center",
            bbox_to_anchor=(centro, 0.02),
            ncol=len(handles),
            fontsize=8,
            frameon=False,
        )
    return figura.legend(
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
    leyenda = None
    if items is not None:
        _quitar_leyendas(figura)
        leyenda = _leyenda_catalogo(figura, items, modo)
        if not datos.get("sospechosos", True):
            _quitar_sospechosos(figura)
        _ajustar_localidades(figura, modo, datos.get("eventos"))
    elif not datos.get("leyenda", True):
        _quitar_leyendas(figura)
    if modo == "perfil" and figura.axes:
        figura.canvas.draw()
        perfil = figura.axes[-1]
        bbox = perfil.get_window_extent().transformed(
            figura.dpi_scale_trans.inverted()
        )
        if leyenda is not None:
            try:
                bbox_leyenda = leyenda.get_window_extent(
                    figura.canvas.get_renderer()
                ).transformed(figura.dpi_scale_trans.inverted())
                bbox = Bbox.union([bbox, bbox_leyenda])
            except Exception:
                pass
        figura.savefig(sys.argv[1], dpi=110, bbox_inches=bbox)
    else:
        figura.savefig(sys.argv[1], dpi=110, bbox_inches="tight")
    plt.close("all")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
