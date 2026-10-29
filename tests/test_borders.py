"""Pruebas de la distancia a la frontera chilena."""

from __future__ import annotations

from types import SimpleNamespace

from shapely.geometry import box
from shapely.prepared import prep

from app.services import borders


def _modulo_basico(resultado):
    return SimpleNamespace(
        frontera_mas_cercana=lambda lat, lon: resultado,
        formatear_frontera=lambda valor: (
            "—"
            if not valor
            else f"{valor[0]} — {float(valor[1]):.1f} km"
        ),
        _cargar_datos=lambda: None,
    )


def test_texto_frontera_formatea_y_vacio(monkeypatch):
    monkeypatch.setattr(
        borders, "_modulo", lambda: _modulo_basico(("Argentina", 12.34))
    )
    assert borders.texto_frontera_coords(-30, -70) == "Argentina — 12.3 km"

    monkeypatch.setattr(borders, "_modulo", lambda: _modulo_basico(None))
    assert borders.texto_frontera_coords(-30, -70) == "—"


def test_anotar_filas_completa_campos(monkeypatch):
    monkeypatch.setattr(
        borders, "_modulo", lambda: _modulo_basico(("Bolivia", 4.25))
    )
    filas = [{"Latitud": "-22", "Longitud": "-68"}]

    borders.anotar_filas(filas, "Latitud", "Longitud")

    assert filas[0]["Frontera_pais"] == "Bolivia"
    assert filas[0]["Frontera_km"] == 4.25
    assert filas[0]["Frontera"] == "Bolivia — 4.2 km"


def _modulo_mar(dist_peru, dist_chile):
    chile = box(-75, -56, -66, -17)
    peru = box(-81, -18, -69, 0)
    bolivia = box(-70, -23, -57, -9)
    argentina = box(-73, -56, -53, -21)
    paises = {
        "CHL": chile,
        "PER": peru,
        "BOL": bolivia,
        "ARG": argentina,
    }
    prep_paises = {clave: prep(geom) for clave, geom in paises.items()}

    def distancia(lon, lat, punto, geom):
        if geom is peru:
            return dist_peru
        if geom is chile:
            return dist_chile
        return 500.0

    return SimpleNamespace(
        frontera_mas_cercana=lambda lat, lon: ("Perú", 50.0),
        formatear_frontera=lambda valor: "Perú — 50.0 km",
        _cargar_datos=lambda: (None, paises, prep_paises),
        _es_mar_chileno=lambda lon, lat, punto, paises, prep_paises: False,
        _distancia_tierra_km=distancia,
        RADIO_MAR_CHILENO_KM=370.4,
    )


def test_mar_peruano_muestra_frontera(monkeypatch):
    monkeypatch.setattr(borders, "_modulo", lambda: _modulo_mar(100.0, 1000.0))

    assert borders.frontera(-18.5, -76.0) == ("Perú", 50.0)


def test_mar_internacional_no_muestra_frontera(monkeypatch):
    monkeypatch.setattr(borders, "_modulo", lambda: _modulo_mar(1000.0, 2000.0))

    assert borders.frontera(-18.5, -76.0) is None


def test_tierra_chilena_no_muestra_frontera(monkeypatch):
    monkeypatch.setattr(borders, "_modulo", lambda: _modulo_mar(100.0, 1000.0))

    assert borders.frontera(-30.0, -70.0) is None


def test_modulo_inexistente_devuelve_vacio(monkeypatch):
    def falla():
        raise ModuleNotFoundError("sin core")

    monkeypatch.setattr(borders, "_modulo", falla)

    assert borders.texto_frontera_coords(-30, -70) == "—"
    assert borders.frontera(-30, -70) is None
