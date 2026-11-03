"""La app no debe depender de ids ni formatos históricos."""

from __future__ import annotations

import json

import pytest

from app.domain.catalogs import manifest
from app.services import (
    analysts,
    attribution,
    catalog_export,
    colores,
    detail,
    plots,
    results,
    sources,
)


@pytest.fixture()
def manifiesto(tmp_path, monkeypatch):
    ruta = tmp_path / "sources.json"
    ruta.write_text(
        json.dumps(
            {
                "version": 1,
                "sources": [
                    {
                        "id": "publico",
                        "label": "Catálogo Nacional",
                        "role": "reference",
                        "format": "referencia",
                        "validator": "eventquery",
                        "download_handler": "eventquery",
                        "visible_in_observaciones": False,
                    },
                    {
                        "id": "red_norte",
                        "label": "Red Norte",
                        "role": "local",
                        "format": "local_export",
                        "validator": "seiscomp",
                        "availability": "seiscomp",
                        "default_primary": True,
                    },
                    {
                        "id": "red_sur",
                        "label": "Red Sur",
                        "role": "local",
                        "format": "local_select",
                        "validator": "seisan",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CATALOG_SOURCES_MANIFEST", str(ruta))
    manifest._leer.cache_clear()
    yield ruta
    manifest._leer.cache_clear()


def test_identidad_desde_manifiesto(manifiesto):
    assert sources.locales() == ["red_norte", "red_sur"]
    assert sources.referencia() == "publico"
    assert sources.etiqueta("red_norte") == "Red Norte"
    assert sources.formato("red_norte") == "local_export"
    assert sources.es_referencia("publico")
    assert not sources.es_referencia("red_norte")
    assert manifest.default_primary() == "red_norte"


def test_columnas_de_analista_dinamicas(manifiesto):
    campos = analysts.campos_analista()
    assert "analista_red_norte" in campos
    assert "analista_red_sur" in campos
    assert analysts.nombres_de_fila(
        {"analista_red_norte": "Red Norte: Ana; Red Sur: Beto"}
    ) == ["ana", "beto"]


def test_repetidos_por_capacidad_y_label(manifiesto):
    opciones = {clave: (archivo, titulo) for clave, archivo, titulo in results.rep_files(
        ["red_norte", "red_sur"]
    )}
    assert opciones["red_norte_amplio"][1] == "Red Norte · amplio"
    assert opciones["red_sur_exclu"][0] == "rep_red_sur_exclu.txt"
    assert "red_norte_exclu" not in opciones


def test_indice_usa_ids_reales(manifiesto, tmp_path):
    workspace = tmp_path / "ws"
    datos = workspace / "datos"
    datos.mkdir(parents=True)
    (datos / "new_2_publico.csv").write_text(
        ",Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Percep.\n"
        "0,2026-10-01 00:00:00,-30.0,-71.0,10.0,2.5,ML,S\n",
        encoding="utf-8",
    )
    (datos / "salida_collect.csv").write_text(
        ",Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista\n"
        "0,2026-10-01 00:00:00,-30.0,-71.0,10.0,2.5,ML,ana\n",
        encoding="utf-8",
    )
    (datos / "seiscomp_parametros.csv").write_text(
        ",Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista\n"
        "0,2026-10-01 00:00:00,-30.0,-71.0,10.0,2.5,ML,beto\n",
        encoding="utf-8",
    )

    indice = results.construir_resultados(workspace)

    assert set(indice["catalogos"]) == {"publico", "red_norte", "red_sur"}
    assert indice["catalogos"]["publico"]["archivo"] == "resultados/catalogo_publico.csv"
    assert (workspace / "resultados/catalogo_publico.csv").is_file()


def test_colores_y_render_por_rol_y_capacidad(manifiesto):
    assert plots._datos_fuente("publico") == ("eventquery", "Catálogo Nacional")
    assert plots._datos_fuente("red_norte") == ("Red Norte", "Red Norte")
    assert colores.color_relleno("publico", {"percibido": "S"}) == colores.COLOR_PERCIBIDO
    assert colores.color_relleno("red_norte", {"percibido": "S"}) == colores.COLOR_NO_PERCIBIDO
    assert detail.etiqueta_fuente("red_norte") == "Red Norte"
    assert plots._fuente("catalogos", "red_norte") == "red_norte"
    assert plots._fuente("repetidos", "red_norte_amplio") == "red_norte"


def test_leyenda_sin_nombres_de_fuente():
    items = catalog_export._leyenda_items(
        [
            {"percibido": "N"},
            {"percibido": "S"},
        ]
    )
    assert [item["etiqueta"] for item in items] == [
        "Sismo no percibido",
        "Sismo percibido",
    ]


def test_atribucion_usa_labels_del_manifiesto(manifiesto, tmp_path):
    datos = tmp_path / "datos"
    datos.mkdir()
    cabecera = (
        "fecha_eventquery,lat_eventquery,lon_eventquery,"
        "analista,dt_seg,fuente\n"
    )
    (datos / "atribucion_red_norte.csv").write_text(
        cabecera + "2026-10-01 00:00:00,-30.0,-71.0,Ana,0.0,red_norte\n",
        encoding="utf-8",
    )
    (datos / "atribucion_red_sur.csv").write_text(
        cabecera + "2026-10-01 00:00:00,-30.0,-71.0,Beto,0.0,red_sur\n",
        encoding="utf-8",
    )

    indices = attribution.indices_atribucion(tmp_path)
    texto = attribution.texto_analista_probable(
        indices, "2026-10-01 00:00:00", -30.0, -71.0
    )

    assert texto == "Red Norte: Ana; Red Sur: Beto"
