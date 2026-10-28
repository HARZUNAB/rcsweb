"""Pruebas de construcción y lectura de las tablas de resultados."""

from __future__ import annotations

from app.services.results import construir_resultados, leer_tabla


def _escribir(workspace, relativa, contenido):
    ruta = workspace / relativa
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(contenido, encoding="utf-8")
    return ruta


def _preparar_workspace(tmp_path):
    workspace = tmp_path / "ws"
    _escribir(
        workspace,
        "datos/no_pub_desde_2_5_estricto.csv",
        ",Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista,"
        "Publicado_en,Estado,Dt_otra_seg,Dist_otra_km,Analista_otra\n"
        "0,2026-10-13 09:55:59,-23.007,-69.027,128.5,2.8,ML,elena,,"
        "Sin coincidencia,,,\n",
    )
    _escribir(
        workspace,
        "datos/atribucion_seisan.csv",
        "n_fila_eventquery,fecha_eventquery,lat_eventquery,lon_eventquery,"
        "prof_eventquery,mag_eventquery,tipo_mag_eventquery,percibido,"
        "fecha_local,lat_local,lon_local,prof_local,mag_local,tipo_mag_local,"
        "analista,dt_seg,dlat,dlon,dist_km,n_candidatos,fuente\n"
        "0,2026-10-03 15:53:56,-29.519,-72.594,30.0,2.8,ML,S,"
        "2026-10-03  15:53:56,-29.519,-72.594,30.0,2.8,ML,beto,0.0,0.0,0.0,0.0,1,seisan\n"
        "2,2026-10-05 13:10:57,-21.157,-70.324,50.0,3.2,ML,S,"
        "2026-10-05  13:10:57,-21.157,-70.324,44.3,2.7,ML,dani,0.0,0.0,0.0,0.0,1,seisan\n",
    )
    _escribir(
        workspace,
        "informes/rep_publica_estricto.txt",
        "fecha_hora\tlatitud\tlongitud\tprof\tmag\ttipomag\treferencia\tpercibido\n"
        "2026-10-03 15:53:56\t-29.519\t-72.594\t30.0\t2.8\tML\tCoquimbo\tS\n"
        "2026-10-03 15:53:57\t-29.519\t-72.594\t30.0\t2.8\tML\tCoquimbo\tS\n",
    )
    _escribir(
        workspace,
        "datos/salida_collect.csv",
        ",Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista\n"
        "0,2026-10-03  15:53:56,-29.519,-72.594,30.0,2.8,ML,beto\n",
    )
    return workspace


def test_construir_resultados_normaliza_y_cuenta(app, tmp_path):
    workspace = _preparar_workspace(tmp_path)

    with app.app_context():
        indice = construir_resultados(workspace)

    assert indice["no_publicados"]["seisan"]["filas"] == 1
    assert indice["no_actualizados"]["seisan"]["filas"] == 1
    assert indice["repetidos"]["publica_estricto"]["filas"] == 2
    assert indice["catalogos"]["seisan"]["filas"] == 1

    no_pub = (workspace / "resultados/no_publicados_seisan.csv").read_text(encoding="utf-8-sig")
    assert no_pub.splitlines()[0].startswith("Fecha_Hora")
    assert "elena" in no_pub

    no_act = (workspace / "resultados/no_actualizados_seisan.csv").read_text(encoding="utf-8-sig")
    assert "dani" in no_act
    assert "beto" not in no_act
    assert "prof, mag" in no_act


def test_leer_tabla_busca_ordena_y_pagina(app, tmp_path):
    workspace = _preparar_workspace(tmp_path)
    with app.app_context():
        construir_resultados(workspace)

    tabla = leer_tabla(workspace, "no_publicados_seisan.csv")
    assert tabla["existe"] is True
    assert tabla["total"] == 1
    assert tabla["columnas"][0] == "Fecha_Hora"

    filtrada = leer_tabla(workspace, "no_publicados_seisan.csv", q="elena")
    assert filtrada["total"] == 1
    vacia = leer_tabla(workspace, "no_publicados_seisan.csv", q="nadie")
    assert vacia["total"] == 0

    repetidos = leer_tabla(workspace, "repetidos_publica_estricto.csv", per_page=1)
    assert repetidos["total"] == 2
    assert repetidos["pages"] == 2
    assert len(repetidos["filas"]) == 1
    segunda = leer_tabla(workspace, "repetidos_publica_estricto.csv", per_page=1, page=2)
    assert segunda["page"] == 2
    assert len(segunda["filas"]) == 1


def test_leer_tabla_no_permite_salir_del_workspace(app, tmp_path):
    workspace = _preparar_workspace(tmp_path)
    with app.app_context():
        construir_resultados(workspace)

    tabla = leer_tabla(workspace, "../../etc/passwd")
    assert tabla["existe"] is False
    assert tabla["filas"] == []
