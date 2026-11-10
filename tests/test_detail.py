"""Pruebas del detalle de evento y de los grupos de repetidos."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from app.extensions import db
from app.models import Job, nuevo_uuid
from app.services.detail import (
    clave_evento,
    construir_detalle,
    leer_filas,
    puntos_mapa,
)
from app.services.workspace import crear_workspace


def _fila_no_actualizada():
    return {
        "fecha_local": "2026-10-03  15:53:56",
        "lat_local": "-29.519",
        "lon_local": "-72.594",
        "prof_local": "30.0",
        "mag_local": "2.8",
        "tipo_mag_local": "ML",
        "fecha_eventquery": "2026-10-03 15:53:56",
        "lat_eventquery": "-29.520",
        "lon_eventquery": "-72.594",
        "prof_eventquery": "31.0",
        "mag_eventquery": "3.0",
        "tipo_mag_eventquery": "ML",
        "analista": "beto",
        "dt_seg": "1.0",
        "dlat": "-0.001",
        "dlon": "0.0",
        "dist_km": "0.1",
        "discrepancias": "lat, prof, mag",
    }


def test_puntos_mapa_no_actualizados():
    fila = _fila_no_actualizada()
    contexto = construir_detalle("no_actualizados", "no_actualizados_seisan.csv", [fila], 0)
    puntos = puntos_mapa(
        "no_actualizados",
        contexto["fila"],
        "seisan",
        analista_publicado="SeisComp: cris; Seisan: beto",
        indice=0,
    )

    assert len(puntos) == 2
    assert {p["fuente"] for p in puntos} == {"seisan", "eventquery"}
    assert all(p["fila"] == 0 for p in puntos)
    assert puntos[0]["fuente"] == "seisan"
    assert puntos[0]["dist_km"] == 0.1
    assert puntos[0]["comparacion"] is True
    assert puntos[0]["referencia"] is False
    assert puntos[0]["analista"] == "beto"
    assert puntos[0]["analista_etiqueta"] == "Analista"
    assert puntos[1]["fuente"] == "eventquery"
    assert puntos[1]["dist_km"] == 0.0
    assert puntos[1]["comparacion"] is True
    assert puntos[1]["referencia"] is True
    assert puntos[1]["analista"] == "SeisComp: cris; Seisan: beto"
    assert puntos[1]["analista_etiqueta"] == "Analista probable"
    assert all(p["color"].startswith("#") for p in puntos)


def test_puntos_mapa_no_actualizados_sin_publicado_usa_local():
    fila = _fila_no_actualizada()
    fila["lat_eventquery"] = ""
    fila["lon_eventquery"] = ""

    puntos = puntos_mapa("no_actualizados", fila, "seisan", indice=0)

    assert len(puntos) == 1
    assert puntos[0]["fuente"] == "seisan"
    assert puntos[0]["comparacion"] is False
    assert puntos[0]["referencia"] is False
    assert puntos[0]["fila"] == 0


def test_puntos_mapa_repetidos_referencia_en_cero():
    fila = {
        "fecha_hora": "2026-10-01 00:00:00",
        "latitud": "-30.0",
        "longitud": "-71.0",
        "prof": "10.0",
        "mag": "2.5",
        "tipomag": "ML",
        "analista": "ana",
    }
    otro = {**fila, "latitud": "-30.1", "longitud": "-71.1"}
    grupo = [
        {"_fila": 0, "fila": fila, "dt_seg": 0, "dlat": 0, "dlon": 0},
        {"_fila": 1, "fila": otro, "dt_seg": 1, "dlat": 0.1, "dlon": 0.1},
    ]
    puntos = puntos_mapa("repetidos", fila, "seiscomp_estricto", grupo, indice=0)

    assert len(puntos) == 2
    assert puntos[0]["dist_km"] == 0.0
    assert puntos[0]["fuente"] == "seiscomp"
    assert puntos[0]["comparacion"] is True
    assert puntos[0]["referencia"] is True
    assert puntos[1]["comparacion"] is True
    assert puntos[1]["referencia"] is False
    assert puntos[0]["fila"] == 0
    assert puntos[1]["fila"] == 1


def test_puntos_mapa_evento_unico_sin_comparacion():
    fila = {
        "Fecha_Hora": "2026-10-26 20:39:24",
        "Latitud": "-27.08",
        "Longitud": "-71.81",
        "Prof.": "42.1",
        "Mag.": "3.7",
        "Tipo_mag.": "MLv",
        "Analista": "ana",
        "Estado": "Revisado",
        "Percep.": "",
    }
    puntos = puntos_mapa("no_publicados", fila, "eventquery", indice=0)

    assert len(puntos) == 1
    assert puntos[0]["comparacion"] is False
    assert puntos[0]["referencia"] is False
    assert puntos[0]["dist_km"] == 0.0
    assert puntos[0]["fila"] == 0


def test_puntos_mapa_catalogo_eventquery_usa_analista_probable():
    fila = {
        "Fecha_Hora": "2026-10-01 00:00:00",
        "Latitud": "-30.0",
        "Longitud": "-71.0",
        "Prof.": "10.0",
        "Mag.": "2.5",
        "Tipo_mag.": "ML",
        "Analista probable": "SeisComp: cris; Seisan: beto",
        "Percep.": "",
    }

    puntos = puntos_mapa("catalogos", fila, "eventquery", indice=0)

    assert len(puntos) == 1
    assert puntos[0]["analista"] == "SeisComp: cris; Seisan: beto"
    assert puntos[0]["analista_etiqueta"] == "Analista probable"
    assert puntos[0]["fila"] == 0


def test_distancia_del_encabezado_solo_en_tablas_comparadas():
    fila = _fila_no_actualizada()
    assert construir_detalle("no_actualizados", "x.csv", [fila], 0)["distancia"] == "0.1"

    unica = {"Fecha_Hora": "2026-10-26 20:39:24", "dist_km": "0"}
    assert construir_detalle("no_publicados", "x.csv", [unica], 0)["distancia"] == ""


def test_comparaciones_y_deltas():
    contexto = construir_detalle(
        "no_actualizados", "no_actualizados_seisan.csv", [_fila_no_actualizada()], 0
    )

    comparaciones = {item["parametro"]: item for item in contexto["comparaciones"]}
    assert comparaciones["Latitud"]["delta"] == "-0.001°"
    assert comparaciones["Latitud"]["coincide"] is False
    assert comparaciones["Longitud"]["coincide"] is True
    assert comparaciones["Profundidad"]["delta"] == "+1.0 km"
    assert comparaciones["Profundidad"]["coincide"] is False
    assert comparaciones["Magnitud"]["delta"] == "+0.2"
    assert comparaciones["Magnitud"]["coincide"] is False
    assert comparaciones["Fecha y hora"]["delta"] == "+1.0 s"


def _filas_repetidas():
    base = {
        "latitud": "-29.519",
        "longitud": "-72.594",
        "prof": "30.0",
        "mag": "2.8",
        "tipomag": "ML",
        "referencia": "Coquimbo",
        "percibido": "S",
    }
    return [
        {**base, "fecha_hora": "2026-10-03 15:53:56"},
        {**base, "fecha_hora": "2026-10-03 15:53:57"},
        {**base, "fecha_hora": "2026-10-03 15:54:01"},
        {**base, "fecha_hora": "2026-10-03 15:54:10"},
    ]


def test_grupo_repetidos_estricto_y_amplio():
    filas = _filas_repetidas()

    estricto = construir_detalle("repetidos", "repetidos_publica_estricto.csv", filas, 0)
    assert len(estricto["grupo"]) == 2

    amplio = construir_detalle("repetidos", "repetidos_publica_amplio.csv", filas, 0)
    assert len(amplio["grupo"]) == 3
    assert [item["_fila"] for item in amplio["grupo"]] == [0, 1, 2]


def test_detalle_no_publicado_tiene_campos():
    contexto = construir_detalle("no_publicados", "x.csv", [{"Fecha_Hora": "x"}], 0)

    assert len(contexto["campos_local"]) == 7
    assert len(contexto["campos_otra"]) == 5


def test_leer_filas_no_permite_salir_del_workspace(tmp_path):
    workspace = tmp_path / "ws"
    (workspace / "resultados").mkdir(parents=True)
    assert leer_filas(workspace, "../../etc/passwd") is None
    assert leer_filas(workspace, "no_existe.csv") is None


def test_ruta_detalle_renderiza(app, client, login, tmp_path):
    login()
    job = Job(
        id=nuevo_uuid(),
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 31, tzinfo=UTC),
        status="done",
    )
    db.session.add(job)
    db.session.commit()
    workspace = crear_workspace(job.id)
    (workspace / "resultados").mkdir(parents=True, exist_ok=True)
    columnas = (
        "fecha_local,lat_local,lon_local,prof_local,mag_local,tipo_mag_local,"
        "fecha_eventquery,lat_eventquery,lon_eventquery,prof_eventquery,"
        "mag_eventquery,tipo_mag_eventquery,analista,dt_seg,dlat,dlon,dist_km,"
        "publicacion_probable,revision,revision_orden,discrepancias\n"
    )
    valores = (
        "2026-10-03  15:53:56,-29.519,-72.594,30.0,2.8,ML,"
        "2026-10-03 15:53:56,-29.520,-72.594,31.0,3.0,ML,beto,"
        "1.0,-0.001,0.0,0.1,Esta fuente,Alta,1,lat, prof, mag\n"
    )
    (workspace / "resultados" / "no_actualizados_seisan.csv").write_text(
        columnas + valores, encoding="utf-8"
    )

    respuesta = client.get(f"/jobs/{job.id}/resultados/no_actualizados/seisan/0")

    assert respuesta.status_code == 200
    html = respuesta.get_data(as_text=True)
    assert "Comparación de parámetros" in html
    assert "Latitud" in html
    assert "Alta" in html
    datos = json.loads(
        re.search(
            r'<script type="application/json" id="mapa-datos">(.*?)</script>',
            html,
            re.S,
        ).group(1)
    )
    assert all(punto["fila"] == 0 for punto in datos)
    assert all(
        "/resultados/no_actualizados/seisan/0" in punto["url"]
        for punto in datos
    )

    assert client.get(f"/jobs/{job.id}/resultados/no_actualizados/seisan/99").status_code == 404


def test_detalle_no_actualizados_publicado_muestra_analista_probable(
    app, client, login, tmp_path
):
    login()
    job = Job(
        id=nuevo_uuid(),
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 31, tzinfo=UTC),
        status="done",
    )
    db.session.add(job)
    db.session.commit()
    workspace = crear_workspace(job.id)
    (workspace / "resultados").mkdir(parents=True, exist_ok=True)
    columnas = (
        "fecha_local,lat_local,lon_local,prof_local,mag_local,tipo_mag_local,"
        "fecha_eventquery,lat_eventquery,lon_eventquery,prof_eventquery,"
        "mag_eventquery,tipo_mag_eventquery,analista,dt_seg,dlat,dlon,dist_km,"
        "publicacion_probable,revision,revision_orden,discrepancias\n"
    )
    valores = (
        "2026-10-03  15:53:56,-29.519,-72.594,30.0,2.8,ML,"
        "2026-10-03 15:53:56,-29.520,-72.594,31.0,3.0,ML,beto,"
        "1.0,-0.001,0.0,0.1,Esta fuente,Alta,1,lat, prof, mag\n"
    )
    (workspace / "resultados" / "no_actualizados_seisan.csv").write_text(
        columnas + valores, encoding="utf-8"
    )
    (workspace / "datos").mkdir(parents=True, exist_ok=True)
    for fuente, analista in (("seiscomp", "cris"), ("seisan", "beto")):
        (
            workspace / "datos" / f"atribucion_{fuente}.csv"
        ).write_text(
            "fecha_eventquery,lat_eventquery,lon_eventquery,analista,"
            "dt_seg,fuente\n"
            f"2026-10-03 15:53:56,-29.520,-72.594,{analista},0.0,{fuente}\n",
            encoding="utf-8",
        )

    respuesta = client.get(
        f"/jobs/{job.id}/resultados/no_actualizados/seisan/0",
        query_string={"mapa": "offline"},
    )

    assert respuesta.status_code == 200
    html = respuesta.get_data(as_text=True)
    datos = json.loads(
        re.search(
            r'<script type="application/json" id="mapa-datos">(.*?)</script>',
            html,
            re.S,
        ).group(1)
    )
    publicado = next(p for p in datos if p["rol"] == "publicado")
    local = next(p for p in datos if p["rol"] == "local")
    assert publicado["analista"] == "SeisComp: cris; Seisan: beto"
    assert publicado["analista_etiqueta"] == "Analista probable"
    assert local["analista"] == "beto"
    assert local["analista_etiqueta"] == "Analista"
    assert publicado["fila"] == 0
    assert local["fila"] == 0
    assert "/resultados/no_actualizados/seisan/0" in publicado["url"]
    assert "/resultados/no_actualizados/seisan/0" in local["url"]


def test_clave_evento_empareja_mapa_y_perfil():
    punto_mapa = {
        "fuente": "seiscomp",
        "lat": -33.1234567,
        "lon": -70.1234567,
        "prof": 30.04,
    }
    punto_perfil = {
        "fuente": "seiscomp",
        "lat": -33.1234568,
        "lon": -70.1234566,
        "prof": 30.0,
    }

    assert clave_evento(punto_mapa) == clave_evento(punto_perfil)
    assert clave_evento(punto_mapa) != clave_evento(
        {**punto_mapa, "fuente": "eventquery"}
    )
    assert clave_evento({}) == "|||"


def test_detalle_no_evaluable_muestra_motivo_generico(app, client, login):
    login()
    job = Job(
        id=nuevo_uuid(),
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 31, tzinfo=UTC),
        status="done",
    )
    db.session.add(job)
    db.session.commit()
    workspace = crear_workspace(job.id)
    (workspace / "resultados").mkdir(parents=True, exist_ok=True)
    columnas = (
        "fecha_local,lat_local,lon_local,prof_local,mag_local,tipo_mag_local,"
        "fecha_eventquery,lat_eventquery,lon_eventquery,prof_eventquery,"
        "mag_eventquery,tipo_mag_eventquery,analista,dt_seg,dlat,dlon,dist_km,"
        "publicacion_probable,revision,revision_motivo,revision_orden,"
        "discrepancias\n"
    )
    valores = (
        "2026-10-03 15:53:56,-29.519,-72.594,30.0,2.8,ML,"
        "2026-10-03 15:53:56,-29.520,-72.594,31.0,3.0,ML,beto,"
        "1.0,-0.001,0.0,0.1,No evaluable,—,"
        "falta la atribución de otra fuente de datos,4,lat\n"
    )
    (workspace / "resultados" / "no_actualizados_seisan.csv").write_text(
        columnas + valores, encoding="utf-8"
    )

    respuesta = client.get(
        f"/jobs/{job.id}/resultados/no_actualizados/seisan/0"
    )

    assert respuesta.status_code == 200
    html = respuesta.get_data(as_text=True)
    assert "No evaluable:" in html
    assert "falta la atribución de otra fuente de datos" in html


def test_detalle_no_evaluable_sin_motivo_usa_texto_generico():
    fila = _fila_no_actualizada()
    fila["publicacion_probable"] = "No evaluable"

    detalle = construir_detalle(
        "no_actualizados", "no_actualizados_seisan.csv", [fila], 0
    )

    assert detalle["revision_motivo"] == (
        "falta la atribución de otra fuente de datos"
    )
