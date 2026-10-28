"""Pruebas de atribución de analistas en repetidos publicados."""

from __future__ import annotations

from app.services.attribution import analistas_para_evento, cargar_atribucion
from app.services.results import construir_resultados


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
