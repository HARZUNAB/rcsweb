"""Pruebas de la capa de dominio: registro, adaptadores y catálogo canónico."""

from __future__ import annotations

import json

from app.domain.catalogs.canonical import (
    escribir_desde_csv,
    escribir_extensiones,
    leer_canonico,
    leer_tensores,
    ruta_canonica,
    ruta_tensores,
)
from app.domain.catalogs.registry import adaptador, default_primary, formato
from app.domain.catalogs.schema import SCHEMA_VERSION


def test_registro_de_formatos():
    assert default_primary() == "local_export"
    assert formato("eventquery").rol == "referencia"
    assert formato("eventquery").codigo == "referencia"
    assert formato("seiscomp").es_local
    assert formato("seiscomp").codigo == "local_export"
    assert "inventario" in formato("seiscomp").capacidades
    assert "excluidos" in formato("seisan").capacidades
    assert "percibidos" in formato("eventquery").capacidades
    assert SCHEMA_VERSION == "1.2"


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


def _workspace_con_evento(tmp_path):
    workspace = tmp_path / "ws"
    catalogo = workspace / "datos" / "seiscomp_parametros.csv"
    catalogo.parent.mkdir(parents=True)
    catalogo.write_text(
        ",Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista,"
        "id_evento,id_origen,base_datos\n"
        "0,2026-10-03 15:53:56,-29.519,-72.594,30.0,2.8,ML,beto,"
        "csn_test_0001,Origin/20261003155356.000,seiscomp\n",
        encoding="utf-8",
    )
    escribir_desde_csv(workspace, "seiscomp", "seiscomp", catalogo)
    return workspace


def test_extension_tensores_normaliza_unidades(tmp_path):
    workspace = _workspace_con_evento(tmp_path)
    tensores = workspace / "datos" / "tensores.csv"
    tensores.write_text(
        "id_evento,id_origen,tensor_id,method,mechanism,strike1,dip1,rake1,"
        "strike2,dip2,rake2,m_rr,m_tt,m_pp,m_rt,m_rp,m_tp,scalar_moment,"
        "moment_units,is_preferred\n"
        "csn_test_0001,Origin/20261003155356.000,t-1,SEISCOMP,DC,"
        "10,20,30,40,50,60,1e25,-1e25,0,0,0,0,1e25,dyn-cm,Si\n",
        encoding="utf-8",
    )

    meta = escribir_extensiones(
        workspace, "seiscomp", "seiscomp", {"tensores": tensores}
    )

    assert ruta_tensores(workspace, "seiscomp").is_file()
    registro = leer_tensores(workspace, "seiscomp")[0]
    assert registro["event_id"] == "seiscomp:000000"
    assert registro["origin_id"] == "Origin/20261003155356.000"
    assert registro["tensor_id"] == "t-1"
    assert registro["method"] == "SEISCOMP"
    assert registro["mechanism"] == "DC"
    assert registro["strike1"] == 10.0
    assert registro["moment_units"] == "Nm"
    assert registro["moment_units_original"] == "dyn-cm"
    assert abs(registro["scalar_moment"] - 1e18) < 1.0
    assert abs(registro["m_rr"] - 1e18) < 1.0
    assert abs(registro["m_tt"] + 1e18) < 1.0
    assert abs(registro["moment_magnitude"] - 5.9333333) < 1e-5
    assert registro["is_preferred"] is True
    assert meta["extensions"]["tensores"]["present"] is True
    assert meta["extensions"]["tensores"]["rows"] == 1


def test_extension_tensores_unidades_desconocidas(tmp_path):
    workspace = _workspace_con_evento(tmp_path)
    tensores = workspace / "datos" / "tensores.csv"
    tensores.write_text(
        "id_evento,id_origen,tensor_id,m_rr,scalar_moment\n"
        "csn_test_0001,Origin/20261003155356.000,t-2,1e25,1e25\n",
        encoding="utf-8",
    )

    escribir_extensiones(
        workspace, "seiscomp", "seiscomp", {"tensores": tensores}
    )

    registro = leer_tensores(workspace, "seiscomp")[0]
    assert registro["moment_units"] == ""
    assert registro["moment_units_original"] == ""
    assert registro["scalar_moment"] == 1e25
    assert registro["m_rr"] == 1e25
    assert registro["moment_magnitude"] is None


def test_catalogo_respeta_publicado_por_evento(tmp_path):
    workspace = tmp_path / "ws"
    catalogo = workspace / "datos" / "central_parametros.csv"
    catalogo.parent.mkdir(parents=True)
    catalogo.write_text(
        ",Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista,"
        "Publicado,Revisión\n"
        "0,2026-10-01 00:00:00,-30.0,-71.0,10.0,2.5,ML,eatl,Sí,Revisado\n"
        "1,2026-10-01 00:01:00,-30.1,-71.1,11.0,2.6,ML,eatl,No,Confirmado\n",
        encoding="utf-8",
    )

    escribir_desde_csv(workspace, "central", "local_db", catalogo)

    eventos = leer_canonico(workspace, "central")
    assert eventos[0]["is_published"] is True
    assert eventos[0]["status"] == "published"
    assert eventos[0]["revision"] == "Revisado"
    assert eventos[1]["is_published"] is False
    assert eventos[1]["status"] == "reported"
    assert eventos[1]["revision"] == "Confirmado"
