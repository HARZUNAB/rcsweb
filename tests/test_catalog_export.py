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


def test_orden_para_mapa_deja_los_percibidos_al_final():
    eventos = [
        {"id": 1, "percibido": "S"},
        {"id": 2, "percibido": "N"},
        {"id": 3},
        {"id": 4, "percibido": "s"},
    ]

    ordenados = catalog_export._orden_para_mapa(eventos)

    assert [evento["id"] for evento in ordenados] == [2, 3, 1, 4]


def test_mapa_planta_sin_leyenda_y_con_percibidos_al_final(
    monkeypatch, tmp_path
):
    llamadas = []

    def falso(*args, **kwargs):
        llamadas.append((args, kwargs))
        return b"png"

    monkeypatch.setattr(catalog_export.plots, "generar_mapa_grupo", falso)
    planta = {
        "clave": "nacional",
        "titulo": "Chile continental",
        "territorio": "Nacional",
        "eventos": [
            {"id": 1, "percibido": "S"},
            {"id": 2, "percibido": "N"},
        ],
        "total": 2,
    }

    catalog_export.mapa_planta(
        tmp_path,
        planta,
        "seisan",
        cache_key="clave",
        resumen={},
    )

    args, kwargs = llamadas[0]
    assert kwargs["leyenda"] is False
    assert kwargs["sospechosos"] is False
    assert [evento["id"] for evento in args[1]] == [2, 1]
    assert catalog_export.VERSION_MAPAS in args[4]


def test_mapa_perfil_sin_leyenda_y_con_percibidos_al_final(
    monkeypatch, tmp_path
):
    llamadas = []

    def falso(*args, **kwargs):
        llamadas.append((args, kwargs))
        return b"png"

    monkeypatch.setattr(catalog_export.plots, "generar_mapa_grupo", falso)
    datos = {
        "eventos": [
            {"perfil": "P001", "percibido": "S"},
            {"perfil": "P001", "percibido": "N"},
            {"perfil": "P002", "percibido": "N"},
        ]
    }

    catalog_export.mapa_perfil(
        tmp_path,
        datos,
        "seisan",
        "P001",
        cache_key="clave",
        resumen={},
        modo="perfil",
    )

    args, kwargs = llamadas[0]
    assert kwargs["leyenda"] is False
    assert kwargs["sospechosos"] is False
    assert [evento["percibido"] for evento in args[1]] == ["N", "S"]
    assert catalog_export.VERSION_MAPAS in args[4]


def test_preparar_catalogo_usa_cache_por_archivo(monkeypatch, tmp_path):
    catalog_export.limpiar_cache()
    columnas = ["Fecha_Hora", "Latitud", "Longitud", "Prof.", "Mag.", "Tipo_mag."]
    filas = [
        {
            "Fecha_Hora": "2026-10-01 00:00:00",
            "Latitud": "-30.0",
            "Longitud": "-71.0",
            "Prof.": "10.0",
            "Mag.": "3.0",
            "Tipo_mag.": "ML",
        }
    ]
    llamadas = []

    def leer(*args, **kwargs):
        llamadas.append(args)
        return columnas, filas

    monkeypatch.setattr(catalog_export, "leer_todo", leer)
    monkeypatch.setattr(
        catalog_export.plots, "eventos_catalogo", lambda *args: []
    )
    monkeypatch.setattr(
        catalog_export.panels, "categorizar_territorio", lambda _e: None
    )

    primero = catalog_export.preparar_catalogo(tmp_path, "catalogo.csv", "seisan")
    segundo = catalog_export.preparar_catalogo(tmp_path, "catalogo.csv", "seisan")

    assert primero is segundo
    assert len(llamadas) == 1
