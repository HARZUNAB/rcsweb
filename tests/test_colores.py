"""Pruebas de la paleta base, leyendas y detección de superposiciones."""

from __future__ import annotations

from app.services import colores
from app.services.detail import leyenda_detalle, superpuestos


def test_colores_base():
    assert (
        colores.color_relleno("eventquery", {"percibido": "S"})
        == colores.COLOR_PERCIBIDO
    )
    assert (
        colores.color_relleno("eventquery", {"percibido": "N"})
        == colores.COLOR_NO_PERCIBIDO
    )
    assert (
        colores.color_relleno("seiscomp", {})
        == colores.COLOR_NO_PERCIBIDO
    )
    assert (
        colores.color_relleno(
            "eventquery", {"rol": "publicado", "percibido": "S"}
        )
        == "#ffffff"
    )


def test_estilo_punto_prioriza_publicado_y_sospechoso():
    publicado = colores.estilo_punto(
        "eventquery", {"rol": "publicado"}
    )
    assert publicado["color"] == "#ffffff"
    assert publicado["borde"] == colores.COLOR_PUBLICADO
    assert publicado["borde_ancho"] == 2.0

    sospechoso = colores.estilo_punto(
        "seisan", {"sospechoso": True}
    )
    assert sospechoso["color"] == colores.COLOR_NO_PERCIBIDO
    assert sospechoso["borde"] == colores.COLOR_BORDE_SOSPECHOSO
    assert sospechoso["borde_ancho"] == colores.GROSOR_BORDE_SOSPECHOSO


def test_leyenda_detalle_no_actualizados():
    items = leyenda_detalle(
        "no_actualizados",
        "seiscomp",
        [
            {"rol": "local", "fuente": "seiscomp"},
            {"rol": "publicado", "fuente": "eventquery"},
        ],
        hay_sospechosos=False,
        hay_superpuestos=False,
    )
    etiquetas = [item["etiqueta"] for item in items]
    assert etiquetas == [
        "Evento SeisComp",
        "Publicado",
        "Evento seleccionado",
    ]


def test_leyenda_detalle_eventquery_y_marcas():
    items = leyenda_detalle(
        "catalogos",
        "eventquery",
        [{"fuente": "eventquery"}],
        hay_sospechosos=True,
        hay_superpuestos=True,
    )
    etiquetas = [item["etiqueta"] for item in items]
    assert etiquetas == [
        "Sismo no percibido",
        "Sismo percibido",
        "Sospechoso (borde violeta)",
        "Evento seleccionado",
        "Soluciones superpuestas",
    ]


def test_superpuestos_planta_y_perfil():
    puntos = [
        {"fuente": "seiscomp", "lat": -30.0, "lon": -71.0},
        {"fuente": "eventquery", "lat": -30.0, "lon": -71.0},
        {"fuente": "seiscomp", "lat": -31.0, "lon": -72.0},
    ]
    assert superpuestos(puntos) is True

    mismo = [
        {"fuente": "seiscomp", "lat": -30.0, "lon": -71.0},
        {"fuente": "seiscomp", "lat": -30.0, "lon": -71.0},
    ]
    assert superpuestos(mismo) is False

    perfil = [
        {
            "fuente": "seiscomp",
            "along_km": 10.0,
            "prof": 20.0,
        },
        {
            "fuente": "eventquery",
            "along_km": 10.0,
            "prof": 20.0,
        },
    ]
    assert superpuestos(perfil, perfil=True) is True
