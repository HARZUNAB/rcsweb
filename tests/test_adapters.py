"""Pruebas de la capa de dominio: registro, adaptadores y catálogo canónico."""

from __future__ import annotations

import json

from app.domain.catalogs.canonical import (
    escribir_desde_csv,
    leer_canonico,
    ruta_canonica,
)
from app.domain.catalogs.registry import adaptador, default_primary, formato
from app.domain.catalogs.schema import SCHEMA_VERSION


def test_registro_de_formatos():
    assert default_primary() == "seiscomp"
    assert formato("eventquery").rol == "referencia"
    assert formato("seiscomp").es_local
    assert "inventario" in formato("seiscomp").capacidades
    assert "excluidos" in formato("seisan").capacidades
    assert SCHEMA_VERSION == "1.0"


def test_adaptadores_entregan_plan_y_catalogo():
    job = type("Job", (), {"inicio14": "20261001000000", "fin14": "20261031235959"})()

    eq = adaptador("eventquery")
    assert eq.catalogo(job, "eventquery.csv") == "datos/new_2_eventquery.csv"
    assert [p.clave for p in eq.pasos(job, "eventquery.csv")] == ["normalizar_eventquery"]

    sc = adaptador("seiscomp")
    assert sc.catalogo(job, "eventquery.csv") == "datos/seiscomp_parametros.csv"
    assert sc.prefijo == "seiscomp_"
    assert [p.clave for p in sc.pasos(job, "eventquery.csv")] == ["convertir_seiscomp"]

    se = adaptador("seisan")
    assert se.catalogo(job, "eventquery.csv") == "datos/salida_collect.csv"
    assert [p.clave for p in se.pasos(job, "eventquery.csv")] == [
        "normalizar_seisan",
        "armar_catalogo",
    ]


def test_catalogo_canonico_desde_csv(tmp_path):
    workspace = tmp_path / "ws"
    ruta = workspace / "datos" / "salida_collect.csv"
    ruta.parent.mkdir(parents=True)
    ruta.write_text(
        ",Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista\n"
        "0,2026-10-03  15:53:56,-29.519,-72.594,30.0,2.8,ML,beto\n",
        encoding="utf-8",
    )

    destino = escribir_desde_csv(workspace, "fuente_a", "seisan", ruta)

    assert destino == ruta_canonica(workspace, "fuente_a")
    lineas = destino.read_text(encoding="utf-8").splitlines()
    assert len(lineas) == 1
    evento = json.loads(lineas[0])
    assert evento["source_id"] == "fuente_a"
    assert evento["event_id"] == "fuente_a:000000"
    assert evento["latitude"] == -29.519
    assert evento["depth_km"] == 30.0
    assert evento["analyst"] == "beto"
    assert evento["is_published"] is False
    assert evento["raw"]["Fecha_Hora"] == "2026-10-03  15:53:56"

    assert leer_canonico(workspace, "fuente_a")[0]["source_id"] == "fuente_a"


def test_catalogo_eventquery_se_marca_publicado(tmp_path):
    workspace = tmp_path / "ws"
    ruta = workspace / "datos" / "new_2_eventquery.csv"
    ruta.parent.mkdir(parents=True)
    ruta.write_text(
        ",Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Referencia,Percep.\n"
        "0,2026-10-03 15:53:56,-29.519,-72.594,30.0,2.8,ML,Coquimbo,S\n",
        encoding="utf-8",
    )

    escribir_desde_csv(workspace, "eventquery", "eventquery", ruta)
    evento = leer_canonico(workspace, "eventquery")[0]

    assert evento["is_published"] is True
    assert evento["status"] == "published"
