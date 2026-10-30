"""Pruebas de atribución de analistas en repetidos publicados."""

from __future__ import annotations

from app.services.attribution import (
    analistas_para_evento,
    cargar_atribucion,
    enriquecer_eventquery,
    indices_atribucion,
    texto_analista_probable,
)
from app.services.results import cargar_indice, construir_resultados


def _escribir(workspace, relativa, contenido):
    ruta = workspace / relativa
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(contenido, encoding="utf-8")
    return ruta


def _atribucion(workspace):
    return _escribir(
        workspace,
        "datos/atribucion_seisan.csv",
        "fecha_eventquery,lat_eventquery,lon_eventquery,analista,dt_seg,fuente\n"
        "2026-10-03 15:53:56,-29.519,-72.594,beto,0.0,seisan\n"
        "2026-10-03 15:53:56,-10.000,-60.000,lejano,2.0,seisan\n"
        "2026-10-05 13:10:57,-21.157,-70.324,dani,1.0,seisan\n",
    )


def _atribucion_seiscomp(workspace):
    return _escribir(
        workspace,
        "datos/atribucion_seiscomp.csv",
        "fecha_eventquery,lat_eventquery,lon_eventquery,analista,dt_seg,fuente\n"
        "2026-10-03 15:53:56,-29.519,-72.594,cris,0.1,seiscomp\n",
    )


def _catalogo_eventquery(workspace):
    return _escribir(
        workspace,
        "datos/new_2_eventquery.csv",
        ",Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Referencia,Percep.\n"
        "0,2026-10-03 15:53:56,-29.519,-72.594,30.0,2.8,ML,Coquimbo,S\n",
    )


def _indice_eventquery_crudo(workspace):
    return _escribir(
        workspace,
        "resultados/indice.json",
        '{"catalogos": {"eventquery": {"archivo": "datos/new_2_eventquery.csv", "filas": 1}}}',
    )


def test_cargar_atribucion_y_buscar_analistas(tmp_path):
    workspace = tmp_path / "ws"
    _atribucion(workspace)

    indice = cargar_atribucion(workspace, "seisan")
    assert indice is not None

    encontrados = analistas_para_evento(indice, "2026-10-03  15:53:56", -29.519, -72.594)
    assert encontrados is not None
    assert encontrados[0]["fuente"] == "seisan"
    assert encontrados[0]["analistas"] == ["beto"]

    assert analistas_para_evento(indice, "2026-01-01 00:00:00", 0, 0) is None
    assert cargar_atribucion(workspace, "seiscomp") is None


def test_construir_resultados_agrega_analistas(app, tmp_path):
    workspace = tmp_path / "ws"
    _atribucion(workspace)
    _escribir(
        workspace,
        "informes/rep_publica_estricto.txt",
        "fecha_hora\tlatitud\tlongitud\tprof\tmag\ttipomag\treferencia\tpercibido\n"
        "2026-10-03 15:53:56\t-29.519\t-72.594\t30.0\t2.8\tML\tCoquimbo\tS\n"
        "2026-10-03 15:53:57\t-29.519\t-72.594\t30.0\t2.8\tML\tCoquimbo\tS\n",
    )

    with app.app_context():
        indice = construir_resultados(workspace)

    assert "analista_seisan" in indice["repetidos"]["publica_estricto"]["columnas"]
    texto = (workspace / "resultados/repetidos_publica_estricto.csv").read_text(
        encoding="utf-8-sig"
    )
    assert "analista_seisan" in texto
    assert "beto" in texto
    assert "lejano" not in texto


def test_texto_analista_probable_combina_fuentes(tmp_path):
    workspace = tmp_path / "ws"
    _atribucion(workspace)
    _atribucion_seiscomp(workspace)

    indices = indices_atribucion(workspace)

    texto = texto_analista_probable(
        indices, "2026-10-03 15:53:56", -29.519, -72.594
    )
    assert texto == "SeisComp: cris; Seisan: beto"


def test_enriquecer_eventquery_agrega_columna(tmp_path):
    workspace = tmp_path / "ws"
    _atribucion(workspace)
    _atribucion_seiscomp(workspace)
    columnas = ["Fecha_Hora", "Latitud", "Longitud"]
    filas = [
        {
            "Fecha_Hora": "2026-10-03 15:53:56",
            "Latitud": "-29.519",
            "Longitud": "-72.594",
        }
    ]

    columnas, filas = enriquecer_eventquery(workspace, columnas, filas)

    assert "Analista probable" in columnas
    assert filas[0]["Analista probable"] == "SeisComp: cris; Seisan: beto"


def test_construir_resultados_crea_catalogo_eventquery_enriquecido(app, tmp_path):
    workspace = tmp_path / "ws"
    _atribucion(workspace)
    _atribucion_seiscomp(workspace)
    _catalogo_eventquery(workspace)

    with app.app_context():
        indice = construir_resultados(workspace)

    info = indice["catalogos"]["eventquery"]
    assert info["archivo"] == "resultados/catalogo_eventquery.csv"
    assert info["filas"] == 1
    texto = (workspace / "resultados/catalogo_eventquery.csv").read_text(
        encoding="utf-8-sig"
    )
    assert "Analista probable" in texto
    assert "SeisComp: cris; Seisan: beto" in texto


def test_cargar_indice_genera_catalogo_eventquery_existente(tmp_path):
    workspace = tmp_path / "ws"
    _atribucion(workspace)
    _atribucion_seiscomp(workspace)
    _catalogo_eventquery(workspace)
    _indice_eventquery_crudo(workspace)

    indice = cargar_indice(workspace)

    info = indice["catalogos"]["eventquery"]
    assert info["archivo"] == "resultados/catalogo_eventquery.csv"
    texto = (workspace / "resultados/catalogo_eventquery.csv").read_text(
        encoding="utf-8-sig"
    )
    assert "Analista probable" in texto
    assert "SeisComp: cris; Seisan: beto" in texto
