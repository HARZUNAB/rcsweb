"""Pruebas del detalle de evento y de los grupos de repetidos."""

from __future__ import annotations

from datetime import UTC, datetime

from app.extensions import db
from app.models import Job, nuevo_uuid
from app.services.detail import construir_detalle, leer_filas, puntos_mapa
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
    puntos = puntos_mapa("no_actualizados", contexto["fila"], "seisan")

    assert len(puntos) == 2
    assert {p["fuente"] for p in puntos} == {"seisan", "eventquery"}
    assert puntos[0]["dist_km"] == 0.0
    assert all(p["color"].startswith("#") for p in puntos)


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

    assert client.get(f"/jobs/{job.id}/resultados/no_actualizados/seisan/99").status_code == 404
