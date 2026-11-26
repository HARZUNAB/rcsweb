"""Pruebas del catálogo canónico extendido y su exportación."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.domain.catalogs import canonical
from app.extensions import db
from app.models import Job, JobSource, User, nuevo_uuid
from app.services import catalogo_completo as servicio
from app.services.workspace import crear_workspace, ruta_workspace


def _evento() -> dict:
    return {
        "source_id": "seiscomp",
        "event_id": "seiscomp:000001",
        "source_event_id": "csn_sc1",
        "origin_id": "NLL.1",
        "database": "seiscomp2",
        "event_time": "2026-01-01 00:00:00",
        "latitude": -30.0,
        "longitude": -71.0,
        "depth_km": 35.0,
        "magnitude": 4.5,
        "magnitude_type": "MLv",
        "agency": "CSN",
        "analyst": "ana",
        "status": "published",
        "revision": "reviewed",
        "is_preferred": True,
        "is_published": True,
        "raw_index": 0,
        "origin_quality": {
            "source": "seiscomp",
            "derived": False,
            "used_phase_count": 12,
            "associated_phase_count": 20,
            "used_station_count": 10,
            "associated_station_count": 14,
            "depth_phase_count": 2,
            "standard_error": 0.25,
            "azimuthal_gap": 120.0,
            "secondary_azimuthal_gap": 130.0,
            "ground_truth_level": "A",
            "minimum_distance_km": 55.6,
            "maximum_distance_km": 222.4,
            "median_distance_km": 133.4,
        },
        "origin_uncertainty": {
            "source": "seiscomp",
            "derived": False,
            "time": {
                "value": 0.1,
                "lower": 0.05,
                "upper": 0.2,
                "confidence": 0.9,
            },
            "latitude": {
                "value": 2.5,
                "lower": None,
                "upper": None,
                "confidence": None,
            },
            "longitude": {
                "value": 3.5,
                "lower": None,
                "upper": None,
                "confidence": None,
            },
            "depth": {
                "value": 4.5,
                "lower": None,
                "upper": None,
                "confidence": None,
            },
            "horizontal": {
                "value": 6.0,
                "min": None,
                "max": None,
                "azimuth_max": None,
            },
            "ellipse": {
                "semimajor": 7.0,
                "semiminor": 5.0,
                "semiintermediate": None,
                "plunge": None,
                "azimuth": None,
                "rotation": None,
            },
            "preferred_description": "ellipse",
            "confidence_level": 0.9,
        },
        "origin_metadata": {
            "source": "seiscomp",
            "derived": False,
            "origin_time_us": 123456,
            "type": "hypocenter",
            "evaluation_mode": "manual",
            "method_id": "LOCSAT",
            "earth_model_id": "iasp91",
            "depth_type": "operator",
        },
        "magnitude_metadata": {
            "source": "seiscomp",
            "derived": False,
            "uncertainty": 0.2,
            "lower_uncertainty": 0.1,
            "upper_uncertainty": 0.3,
            "confidence": 0.9,
            "station_count": 8,
            "azimuthal_gap": 110.0,
            "status": "reviewed",
            "method_id": "ML",
        },
        "raw": {},
    }


def _arribo(residual: float, azimut: float) -> dict:
    return {
        "source_id": "seiscomp",
        "event_id": "seiscomp:000001",
        "source_event_id": "csn_sc1",
        "origin_id": "NLL.1",
        "pick_id": "Pick/1",
        "network": "C1",
        "station": "ABC",
        "location": "",
        "channel": "HNZ",
        "phase": "P",
        "pick_time": "2026-01-01 00:00:10",
        "pick_status": "manual",
        "is_used_in_solution": True,
        "weight": 1.0,
        "polarity": "C",
        "residual": residual,
        "distance_km": 0.5,
        "azimuth": azimut,
        "snr": 12.0,
        "qc": "aprobado",
        "picker_probability": None,
        "time_correction_s": 0.0,
        "pick_author": "ana",
        "pick_agency": "CSN",
        "pick_method": "",
        "station_magnitude": 2.3,
        "station_magnitude_type": "MLv",
        "has_station_magnitude": "Si",
        "station_magnitude_residual": -0.2,
        "station_latitude": -30.5,
        "station_longitude": -71.0,
        "station_elevation_m": 100.0,
        "station_place": "",
        "station_country": "",
        "database": "seiscomp2",
        "raw": {},
    }


def _preparar(app) -> Job:
    usuario = db.session.scalar(select(User).limit(1))
    job = Job(
        id=nuevo_uuid(),
        status="done",
        period_start=datetime(2026, 1, 1, tzinfo=UTC),
        period_end=datetime(2026, 1, 31, tzinfo=UTC),
        created_by_id=usuario.id if usuario else None,
    )
    db.session.add(job)
    db.session.add(
        JobSource(
            job_id=job.id,
            kind="seiscomp",
            alias="SeisComp",
            format="local_export",
            role="local_principal",
            priority=0,
            capabilities=["eventos", "arribos"],
        )
    )
    db.session.commit()
    workspace = crear_workspace(job.id)
    destino = workspace / "catalogo" / "seiscomp"
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "eventos.jsonl").write_text(
        json.dumps(_evento(), ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (destino / "arribos.jsonl").write_text(
        json.dumps(_arribo(-0.2, 90.0), ensure_ascii=False)
        + "\n"
        + json.dumps(_arribo(0.4, 90.0), ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    return job


def test_aplanar_evento_incluye_calidad_e_incertidumbres():
    fila = servicio._aplanar_evento(_evento())
    assert fila["quality_used_phase_count"] == 12
    assert fila["quality_minimum_distance_km"] == 55.6
    assert fila["unc_time_value"] == 0.1
    assert fila["origin_time_us"] == 123456
    assert fila["magnitude_uncertainty"] == 0.2


def test_resumen_estaciones_calcula_rms_y_distancia():
    resumen = servicio._resumen_estaciones(
        [_arribo(-0.2, 90.0), _arribo(0.4, 90.0)],
        {"seiscomp:000001": _evento()},
    )
    assert len(resumen) == 1
    fila = resumen[0]
    assert fila["associated_phases"] == 2
    assert fila["used_phases"] == 2
    assert fila["residual_rms_s"] == pytest.approx(0.3162277)
    assert fila["residual_mean_s"] == pytest.approx(0.1)
    assert fila["residual_max_abs_s"] == pytest.approx(0.4)
    assert fila["distance_min_km"] == pytest.approx(55.5975, abs=0.01)
    assert fila["distance_max_km"] == pytest.approx(55.5975, abs=0.01)
    assert fila["azimuth_mean_deg"] == 90.0
    assert fila["derived"] is True


def test_fecha_texto_acepta_formatos_iso():
    assert (
        servicio.fecha_texto("2026-01-01T00:00:10Z")
        == "2026-01-01 00:00:10"
    )
    assert (
        servicio.fecha_texto("2026-01-01T00:00:10+00:00")
        == "2026-01-01 00:00:10"
    )
    assert servicio.fecha_texto("") == ""


def test_datos_evento_arma_arribos_mapa_y_estaciones(app):
    job = _preparar(app)
    datos = servicio.datos_evento(
        job, "seiscomp", _evento(), "SeisComp"
    )
    assert datos["totales"]["arribos"] == 2
    assert datos["totales"]["usadas"] == 2
    assert datos["totales"]["no_usadas"] == 0
    assert datos["totales"]["estaciones"] == 1
    assert datos["totales"]["estaciones_mapa"] == 1
    assert datos["totales"]["estaciones_sin_coordenadas"] == 0

    assert datos["puntos_mapa"][0]["lat"] == -30.0
    assert datos["puntos_mapa"][0]["lon"] == -71.0
    assert datos["puntos_mapa"][0]["clave"] == "seiscomp:000001"

    estacion = datos["estaciones_mapa"][0]
    assert estacion["red"] == "C1"
    assert estacion["estacion"] == "ABC"
    assert estacion["usada"] is True
    assert len(estacion["fases"]) == 2
    assert estacion["fases"][0]["usada"] == "Sí"

    grupo = datos["grupos"][0]
    assert grupo["etiqueta"] == "C1 ABC"
    assert grupo["total"] == 2
    assert grupo["usadas"] == 2
    assert grupo["filas"][0]["hora"] == "00:00:10"
    assert grupo["filas"][0]["distancia_texto"] == "55.6"

    resumen = datos["estaciones"][0]
    assert resumen["used_phases"] == 2
    assert resumen["residual_rms_texto"] == "0.32"
    assert resumen["distancia_texto"] == "55.6"


def test_datos_evento_avisa_estaciones_sin_coordenadas(app):
    job = _preparar(app)
    ruta = (
        ruta_workspace(job.id)
        / "catalogo"
        / "seiscomp"
        / "arribos.jsonl"
    )
    arribo = _arribo(-0.2, 90.0)
    arribo["station_latitude"] = None
    arribo["station_longitude"] = None
    ruta.write_text(
        json.dumps(arribo, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    datos = servicio.datos_evento(
        job, "seiscomp", _evento(), "SeisComp"
    )
    assert datos["totales"]["estaciones_sin_coordenadas"] == 1
    assert datos["estaciones_mapa"] == []
    assert datos["puntos_mapa"][0]["lat"] == -30.0
    assert datos["tiene_epicentro"] is True
    assert datos["tiene_estaciones_mapa"] is False


def test_generar_zip_con_tres_csv_y_leeme(app):
    job = _preparar(app)
    ruta, totales = servicio.generar(job, "seiscomp")
    assert ruta.is_file()
    assert totales == {"eventos": 1, "arribos": 2, "estaciones": 1}

    with zipfile.ZipFile(ruta) as zf:
        nombres = set(zf.namelist())
        assert nombres == {
            "eventos.csv",
            "eventos.json",
            "arribos.csv",
            "estaciones_resumen.csv",
            "LEEME.txt",
        }
        with zf.open("eventos.json") as bruto:
            eventos_json = json.load(bruto)
        assert eventos_json["2026-01-01 00:00:00"]["event_id"] == (
            "seiscomp:000001"
        )
        assert (
            eventos_json["2026-01-01 00:00:00"]["origin_quality"][
                "used_phase_count"
            ]
            == 12
        )
        with zf.open("eventos.csv") as bruto:
            filas = list(
                csv.DictReader(io.TextIOWrapper(bruto, encoding="utf-8"))
            )
        assert filas[0]["quality_used_phase_count"] == "12"
        assert filas[0]["unc_time_value"] == "0.1"
        with zf.open("estaciones_resumen.csv") as bruto:
            resumen = list(
                csv.DictReader(io.TextIOWrapper(bruto, encoding="utf-8"))
            )
        assert resumen[0]["residual_rms_s"].startswith("0.316")
        assert resumen[0]["distance_min_km"].startswith("55.5")
        assert resumen[0]["derived"] == "True"
        leeme = zf.read("LEEME.txt").decode("utf-8")
        assert "Esquema canónico: 1.3" in leeme
        assert "microsegundos" in leeme
        assert "La vista web muestra un mapa" in leeme
        assert "eventos.json" in leeme
        assert "YYYY-MM-DD HH:MM:SS" in leeme


def test_json_eventos_indexa_por_fecha_y_colision():
    primero = _evento()
    segundo = _evento()
    segundo["event_id"] = "seiscomp:000002"
    sin_fecha = _evento()
    sin_fecha["event_id"] = "seiscomp:000003"
    sin_fecha["event_time"] = None
    fecha_invalida = _evento()
    fecha_invalida["event_id"] = "seiscomp:000004"
    fecha_invalida["event_time"] = "no-es-fecha"

    datos = json.loads(
        servicio._json_eventos(
            [segundo, sin_fecha, fecha_invalida, primero]
        )
    )
    assert datos["2026-01-01 00:00:00"]["event_id"] == "seiscomp:000001"
    assert (
        datos["2026-01-01 00:00:00#seiscomp:000002"]["event_id"]
        == "seiscomp:000002"
    )
    assert datos["sin-fecha#seiscomp:000003"]["event_id"] == (
        "seiscomp:000003"
    )
    assert datos["sin-fecha#seiscomp:000004"]["event_id"] == (
        "seiscomp:000004"
    )


def test_generar_rechaza_fuente_no_habilitada(app):
    job = _preparar(app)
    with pytest.raises(servicio.CatalogoCompletoError):
        servicio.generar(job, "eventquery")


def test_canonico_guarda_bloques_para_seiscomp(tmp_path):
    fila = {
        "": "0",
        "Fecha_Hora": "2026-01-01 00:00:00",
        "Latitud": "-30.0",
        "Longitud": "-71.0",
        "Prof.": "35.0",
        "Mag.": "4.5",
        "Tipo_mag.": "MLv",
        "Analista": "ana",
        "fases": "12",
        "rms": "0.25",
        "azgap": "120",
        "associated_phase_count": "20",
        "used_station_count": "10",
        "associated_station_count": "14",
        "minimum_distance_km": "55.6",
        "maximum_distance_km": "222.4",
        "median_distance_km": "133.4",
        "time_uncertainty": "0.1",
        "time_confidence": "0.9",
        "latitude_uncertainty": "2.5",
        "longitude_uncertainty": "3.5",
        "depth_uncertainty": "4.5",
        "origin_time_us": "123456",
        "origin_type": "hypocenter",
        "magnitude_uncertainty": "0.2",
        "magnitude_station_count": "8",
    }
    normalizado = tmp_path / "normalizado.csv"
    with normalizado.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=list(fila))
        escritor.writeheader()
        escritor.writerow(fila)
    destino = canonical.escribir_desde_csv(
        tmp_path / "ws", "seiscomp", "local_export", normalizado
    )
    evento = json.loads(destino.read_text(encoding="utf-8").splitlines()[0])
    assert evento["origin_quality"]["used_phase_count"] == 12
    assert evento["origin_quality"]["associated_phase_count"] == 20
    assert evento["origin_quality"]["standard_error"] == 0.25
    assert evento["origin_uncertainty"]["time"]["value"] == 0.1
    assert evento["origin_metadata"]["origin_time_us"] == 123456
    assert evento["magnitude_metadata"]["uncertainty"] == 0.2


def _datos_catalogo_filtrados(job=None, opcion="seiscomp"):
    return (
        None,
        "SeisComp",
        {"total": 1, "ids_filtrados": ["seiscomp:000001"]},
        {"filtros_texto": "Sin filtros"},
    )


def test_catalogo_completo_desde_pagina_de_catalogos(
    app, client, login, monkeypatch
):
    job = _preparar(app)
    monkeypatch.setattr(
        "app.blueprints.results._datos_catalogo",
        _datos_catalogo_filtrados,
    )
    login()
    respuesta = client.get(
        f"/jobs/{job.id}/resultados/catalogos/seiscomp/"
        "catalogo-completo.zip"
    )
    assert respuesta.status_code == 200
    assert respuesta.mimetype == "application/zip"
    with zipfile.ZipFile(io.BytesIO(respuesta.data)) as zf:
        assert {
            "eventos.csv",
            "eventos.json",
            "arribos.csv",
            "estaciones_resumen.csv",
            "LEEME.txt",
        } <= set(zf.namelist())
        with zf.open("eventos.csv") as bruto:
            filas = list(
                csv.DictReader(io.TextIOWrapper(bruto, encoding="utf-8"))
            )
        assert len(filas) == 1
        assert filas[0]["event_id"] == "seiscomp:000001"


def test_catalogo_completo_respeta_flag(app, client, login):
    job = _preparar(app)
    app.config["RCS_CATALOGO_COMPLETO_ACTIVO"] = False
    login()
    respuesta = client.get(
        f"/jobs/{job.id}/resultados/catalogos/seiscomp/"
        "catalogo-completo.zip"
    )
    assert respuesta.status_code == 404


def test_catalogo_completo_solo_admin_o_supervisor(
    app, client, login, monkeypatch
):
    job = _preparar(app)
    monkeypatch.setattr(
        "app.blueprints.results._datos_catalogo",
        _datos_catalogo_filtrados,
    )
    usuario = db.session.scalar(select(User).limit(1))
    usuario.role = "analista"
    db.session.commit()
    login()
    respuesta = client.get(
        f"/jobs/{job.id}/resultados/catalogos/seiscomp/"
        "catalogo-completo.zip"
    )
    assert respuesta.status_code == 403


def test_detalle_y_descargas_ya_no_ofrecen_catalogo_completo(
    app, client, login
):
    job = _preparar(app)
    login()
    detalle = client.get(f"/jobs/{job.id}")
    assert detalle.status_code == 200
    assert "Catálogo completo" not in detalle.get_data(as_text=True)

    descargas = client.get(f"/jobs/{job.id}/descargas")
    assert descargas.status_code == 200
    assert "Catálogo completo" not in descargas.get_data(as_text=True)


def test_canonico_deja_bloques_vacios_sin_columnas(tmp_path):
    fila = {
        "": "0",
        "Fecha_Hora": "2026-01-01 00:00:00",
        "Latitud": "-30.0",
        "Longitud": "-71.0",
        "Prof.": "35.0",
        "Mag.": "4.5",
        "Tipo_mag.": "MLv",
        "Analista": "ana",
    }
    normalizado = tmp_path / "normalizado.csv"
    with normalizado.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=list(fila))
        escritor.writeheader()
        escritor.writerow(fila)
    destino = canonical.escribir_desde_csv(
        tmp_path / "ws", "seisan", "local_select", normalizado
    )
    evento = json.loads(destino.read_text(encoding="utf-8").splitlines()[0])
    assert evento["origin_quality"] == {}
    assert evento["origin_uncertainty"] == {}
    assert evento["origin_metadata"] == {}
    assert evento["magnitude_metadata"] == {}


def test_generar_central_incluye_incertidumbre_por_estacion(app):
    usuario = db.session.scalar(select(User).limit(1))
    job = Job(
        id=nuevo_uuid(),
        status="done",
        period_start=datetime(2026, 1, 1, tzinfo=UTC),
        period_end=datetime(2026, 1, 31, tzinfo=UTC),
        created_by_id=usuario.id if usuario else None,
    )
    db.session.add(job)
    db.session.add(
        JobSource(
            job_id=job.id,
            kind="central",
            alias="Central",
            format="local_db",
            role="local_principal",
            priority=0,
            capabilities=["eventos", "arribos"],
        )
    )
    db.session.commit()
    workspace = crear_workspace(job.id)
    destino = workspace / "catalogo" / "central"
    destino.mkdir(parents=True, exist_ok=True)
    evento = _evento()
    evento["source_id"] = "central"
    evento["event_id"] = "central:000001"
    evento["origin_quality"] = {
        "source": "central",
        "derived": False,
        "derived_fields": ["used_phase_count"],
        "used_phase_count": 1,
    }
    arribo = _arribo(-0.2, 90.0)
    arribo["source_id"] = "central"
    arribo["event_id"] = "central:000001"
    arribo["residual"] = None
    arribo["pick_uncertainty"] = 0.2
    (destino / "eventos.jsonl").write_text(
        json.dumps(evento, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (destino / "arribos.jsonl").write_text(
        json.dumps(arribo, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    ruta, totales = servicio.generar(job, "central")
    assert totales == {"eventos": 1, "arribos": 1, "estaciones": 1}
    with zipfile.ZipFile(ruta) as zf:
        with zf.open("estaciones_resumen.csv") as bruto:
            filas = list(
                csv.DictReader(io.TextIOWrapper(bruto, encoding="utf-8"))
            )
    assert filas[0]["uncertainty_count"] == "1"
    assert filas[0]["uncertainty_rms_s"].startswith("0.2")
    assert filas[0]["residual_count"] == "0"


def _url_vista(job) -> str:
    return (
        f"/jobs/{job.id}/resultados/catalogos/seiscomp/eventos-arribos"
    )


def test_vista_eventos_arribos_y_ficha(app, client, login, monkeypatch):
    job = _preparar(app)
    monkeypatch.setattr(
        "app.blueprints.results._datos_catalogo",
        _datos_catalogo_filtrados,
    )
    login()
    url = _url_vista(job)

    respuesta = client.get(url)
    assert respuesta.status_code == 200
    html = respuesta.get_data(as_text=True)
    assert "Eventos y arribos descargados" in html
    assert "Eventos (1)" in html
    assert "Arribos (2)" in html
    assert "Estaciones (1)" in html
    assert "seiscomp:000001" in html
    assert "Ver ficha" in html

    for tab in ("arribos", "estaciones", "leeme"):
        assert client.get(url, query_string={"tab": tab}).status_code == 200

    arribos = client.get(
        url, query_string={"tab": "arribos", "estacion": "ABC"}
    )
    assert arribos.status_code == 200
    texto_arribos = arribos.get_data(as_text=True)
    assert "ABC" in texto_arribos
    assert "distance_km_calc" in texto_arribos
    assert "55.597" in texto_arribos
    assert "evento/seiscomp:000001" in texto_arribos

    leeme = client.get(url, query_string={"tab": "leeme"})
    assert "Esquema canónico" in leeme.get_data(as_text=True)
    assert "Filtros: Sin filtros" in leeme.get_data(as_text=True)

    ficha = client.get(url + "/evento/seiscomp:000001")
    assert ficha.status_code == 200
    texto_ficha = ficha.get_data(as_text=True)
    assert "Calidad" in texto_ficha
    assert "Incertidumbre" in texto_ficha
    assert "mapa-datos" in texto_ficha
    assert "mapa-estaciones-iniciales" in texto_ficha
    assert "Arribos del evento" in texto_ficha
    assert "Estaciones del evento" in texto_ficha
    assert "Mapa completo (perfil)" in texto_ficha
    assert "C1 ABC" in texto_ficha
    assert "00:00:10" in texto_ficha
    assert "55.6" in texto_ficha
    assert "JSON completo" in texto_ficha

    ficha_offline = client.get(
        url + "/evento/seiscomp:000001",
        query_string={"mapa": "offline"},
    )
    assert ficha_offline.status_code == 200
    assert "Offline" in ficha_offline.get_data(as_text=True)

    fuera = client.get(url + "/evento/seiscomp:999999")
    assert fuera.status_code == 404


def test_ficha_evento_sin_arribos(app, client, login, monkeypatch):
    job = _preparar(app)
    ruta = (
        ruta_workspace(job.id)
        / "catalogo"
        / "seiscomp"
        / "arribos.jsonl"
    )
    ruta.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        "app.blueprints.results._datos_catalogo",
        _datos_catalogo_filtrados,
    )
    login()
    url = _url_vista(job) + "/evento/seiscomp:000001"
    respuesta = client.get(url)
    assert respuesta.status_code == 200
    html = respuesta.get_data(as_text=True)
    assert "Este evento no tiene arribos" in html
    assert "mapa-datos" in html
    assert "mapa-estaciones-iniciales" not in html


def test_ficha_evento_sin_epicentro(app, client, login, monkeypatch):
    job = _preparar(app)
    evento = _evento()
    evento["latitude"] = None
    evento["longitude"] = None
    ruta = (
        ruta_workspace(job.id)
        / "catalogo"
        / "seiscomp"
        / "eventos.jsonl"
    )
    ruta.write_text(
        json.dumps(evento, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "app.blueprints.results._datos_catalogo",
        _datos_catalogo_filtrados,
    )
    login()
    url = _url_vista(job) + "/evento/seiscomp:000001"
    respuesta = client.get(url)
    assert respuesta.status_code == 200
    html = respuesta.get_data(as_text=True)
    assert "no tiene coordenadas de epicentro" in html
    assert "mapa-datos" not in html
    assert "Arribos del evento" in html


def test_vista_avisa_trabajo_desactualizado(
    app, client, login, monkeypatch
):
    job = _preparar(app)
    monkeypatch.setattr(
        "app.blueprints.results._datos_catalogo",
        _datos_catalogo_filtrados,
    )
    login()
    url = _url_vista(job)
    html = client.get(url).get_data(as_text=True)
    assert "Trabajo generado con una versión anterior" in html
    ficha = client.get(url + "/evento/seiscomp:000001")
    assert ficha.status_code == 200
    assert (
        "Trabajo generado con una versión anterior"
        in ficha.get_data(as_text=True)
    )


def test_vista_no_avisa_trabajo_actualizado(
    app, client, login, monkeypatch
):
    job = _preparar(app)
    meta = {
        "schema_version": "1.3",
        "source_id": "seiscomp",
        "format": "local_export",
        "quality_blocks": {
            "events": 1,
            "with_origin_quality": 1,
            "with_origin_uncertainty": 1,
            "with_origin_metadata": 1,
            "with_magnitude_metadata": 1,
        },
    }
    ruta = (
        ruta_workspace(job.id)
        / "catalogo"
        / "seiscomp"
        / "meta.json"
    )
    ruta.write_text(
        json.dumps(meta, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "app.blueprints.results._datos_catalogo",
        _datos_catalogo_filtrados,
    )
    login()
    url = _url_vista(job)
    html = client.get(url).get_data(as_text=True)
    assert "Trabajo generado con una versión anterior" not in html


def test_revision_muestra_estaciones_sin_aportar(app, client, login):
    job = _preparar(app)
    ruta = (
        ruta_workspace(job.id)
        / "catalogo"
        / "seiscomp"
        / "estaciones_sin_arribos.jsonl"
    )
    ruta.write_text(
        json.dumps(
            {
                "source_id": "seiscomp",
                "event_id": "seiscomp:000001",
                "network": "C1",
                "station": "NEAR",
                "location": "",
                "channel": "HNZ",
                "streams": "C1.NEAR..HNZ",
                "stream_ids": "C1.NEAR..HNZ",
                "station_latitude": -30.4,
                "station_longitude": -71.0,
                "evidence": "NO_CONSULTADO",
                "waveform_status": "NO_CONSULTADO",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    login()
    respuesta = client.get(
        f"/jobs/{job.id}/indicios",
        query_string={"fuente": "seiscomp", "alcance": "picks"},
    )
    assert respuesta.status_code == 200
    html = respuesta.get_data(as_text=True)
    assert "Filtro activo: Sin aportar" in html
    assert "Quitar filtro" in html
    assert "Sin aportar" in html
    assert "NEAR" in html
    assert "1 + 0" in html

    por_defecto = client.get(
        f"/jobs/{job.id}/indicios",
        query_string={"fuente": "seiscomp"},
    )
    assert por_defecto.status_code == 200
    html_defecto = por_defecto.get_data(as_text=True)
    assert "Filtro activo: Revisión prioritaria" in html_defecto
    assert "Filtrar por sin aportar" in html_defecto


def test_vista_eventos_arribos_permisos_y_flag(
    app, client, login, monkeypatch
):
    job = _preparar(app)
    monkeypatch.setattr(
        "app.blueprints.results._datos_catalogo",
        _datos_catalogo_filtrados,
    )
    url = _url_vista(job)

    app.config["RCS_CATALOGO_COMPLETO_ACTIVO"] = False
    login()
    assert client.get(url).status_code == 404

    app.config["RCS_CATALOGO_COMPLETO_ACTIVO"] = True
    usuario = db.session.scalar(select(User).limit(1))
    usuario.role = "analista"
    db.session.commit()
    login()
    assert client.get(url).status_code == 403
