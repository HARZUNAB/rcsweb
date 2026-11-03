"""Pruebas de territorios y radio de influencia del catálogo."""

from __future__ import annotations

from app.services import catalog_export


def test_radio_influencia_por_magnitud():
    assert catalog_export._radio_influencia("3.9") == 200
    assert catalog_export._radio_influencia("4.0") == 300
    assert catalog_export._radio_influencia("5.5") == 400
    assert catalog_export._radio_influencia("6.1") == 500
    assert catalog_export._radio_influencia("") == 200


def test_evento_otros_dentro_del_radio_va_a_nacional(monkeypatch):
    monkeypatch.setattr(
        catalog_export.ubicacion,
        "distancia_chile_km",
        lambda _lat, _lon: 150.0,
    )
    evento = {"territorio": "Otros", "lat": 0.0, "lon": 0.0, "mag": "3.0"}

    assert catalog_export._categoria_planta(evento) == "Nacional"


def test_evento_otros_fuera_del_radio_queda_en_otros(monkeypatch):
    monkeypatch.setattr(
        catalog_export.ubicacion,
        "distancia_chile_km",
        lambda _lat, _lon: 250.0,
    )
    evento = {"territorio": "Otros", "lat": 0.0, "lon": 0.0, "mag": "3.0"}

    assert catalog_export._categoria_planta(evento) == "Otros"


def test_magnitud_grande_amplia_el_radio(monkeypatch):
    monkeypatch.setattr(
        catalog_export.ubicacion,
        "distancia_chile_km",
        lambda _lat, _lon: 350.0,
    )
    evento = {"territorio": "Otros", "lat": 0.0, "lon": 0.0, "mag": "5.5"}

    assert catalog_export._categoria_planta(evento) == "Nacional"


def test_preparar_catalogo_separa_plantas_por_territorio(monkeypatch, tmp_path):
    columnas = ["Fecha_Hora", "Latitud", "Longitud", "Prof.", "Mag.", "Tipo_mag."]
    filas = [
        {
            "Fecha_Hora": "2026-10-01 00:00:00",
            "Latitud": "-30.0",
            "Longitud": "-71.0",
            "Prof.": "10.0",
            "Mag.": "3.0",
            "Tipo_mag.": "ML",
            "_fila": 0,
        }
    ]
    eventos = [
        {"lat": -30.0, "lon": -71.0, "latitud": -30.0, "longitud": -71.0, "mag": "3.0"},
        {"lat": -27.0, "lon": -109.0, "latitud": -27.0, "longitud": -109.0, "mag": "3.0"},
        {"lat": 0.0, "lon": 0.0, "latitud": 0.0, "longitud": 0.0, "mag": "3.0"},
    ]
    monkeypatch.setattr(catalog_export, "leer_todo", lambda *args, **kwargs: (columnas, filas))
    monkeypatch.setattr(catalog_export.plots, "eventos_catalogo", lambda *args: eventos)

    def categorizar(lista):
        for evento in lista:
            evento["territorio"] = (
                "Insular" if evento["lon"] < -100 else "Otros"
                if evento["lon"] == 0 else "Nacional"
            )

    monkeypatch.setattr(catalog_export.panels, "categorizar_territorio", categorizar)
    monkeypatch.setattr(
        catalog_export.ubicacion,
        "distancia_chile_km",
        lambda _lat, _lon: 250.0,
    )

    datos = catalog_export.preparar_catalogo(
        tmp_path, "catalogo.csv", "seisan"
    )

    assert [planta["clave"] for planta in datos["plantas"]] == [
        "nacional",
        "insular",
        "otros",
    ]
    assert [planta["total"] for planta in datos["plantas"]] == [1, 1, 1]


def test_evento_insular_conserva_su_territorio(monkeypatch):
    monkeypatch.setattr(
        catalog_export.ubicacion,
        "distancia_chile_km",
        lambda _lat, _lon: 250.0,
    )
    evento = {"territorio": "Insular", "lat": 0.0, "lon": 0.0, "mag": "3.0"}

    assert catalog_export._categoria_planta(evento) == "Insular"
