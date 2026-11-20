"""Pruebas de la solicitud de revisión de un evento publicado."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from app.domain.catalogs import canonical
from app.extensions import db
from app.models import Job, User, nuevo_uuid
from app.services import indicios, review_reports
from app.services.workspace import crear_workspace


def _job() -> Job:
    job = Job(
        id=nuevo_uuid(),
        period_start=datetime(2026, 11, 1, tzinfo=UTC),
        period_end=datetime(2026, 11, 30, tzinfo=UTC),
        status="done",
    )
    db.session.add(job)
    db.session.commit()
    return job


def _referencia() -> dict:
    return {
        "source_id": "eventquery",
        "event_id": "eventquery:000127",
        "source_event_id": "",
        "event_time": "2026-11-03 11:51:23",
        "latitude": -22.59,
        "longitude": -68.8,
        "depth_km": 42.0,
        "magnitude": 2.6,
        "magnitude_type": "MLv",
        "raw_index": 127,
        "raw": {"Referencia": "18 km al SE de Calama", "Percep.": "N"},
    }


def _cruce() -> dict:
    return {
        "version": 4,
        "huella": {},
        "extras": {"total": 0, "grupos": []},
        "sin_cruce": {
            "total": 1,
            "eventos": [
                {
                    "fila": 127,
                    "evento": "eventquery:000127",
                    "fecha": "2026-11-03 11:51:23",
                    "lat": -22.59,
                    "lon": -68.8,
                    "profundidad": 42.0,
                    "magnitud": 2.6,
                    "tipo_mag": "MLv",
                    "region": "18 km al SE de Calama",
                    "percibido": "N",
                    "candidato": {
                        "fuente": "seiscomp",
                        "etiqueta": "SeisComp",
                        "evento_local": "seiscomp:000280",
                        "fila_local": 280,
                        "fecha_local": "2026-11-03 11:51:19",
                        "lat": -22.63,
                        "lon": -68.69,
                        "profundidad": 82.9,
                        "magnitud": 2.5,
                        "tipo_mag": "MLv",
                        "analista": "tana",
                        "dt_seg": 4.0,
                        "dist_km": 12.4,
                        "clasificacion": "cercano",
                        "motivo_clasificacion": "Δprofundidad 40.9 km",
                    },
                    "diferencias": {
                        "lat": -0.04,
                        "lon": 0.113,
                        "profundidad": 40.9,
                        "magnitud": -0.1,
                    },
                    "criterio": {
                        "estricto": False,
                        "amplio": True,
                        "texto": (
                            "Fuera del cruce estricto (Δt 4.0 s > 3 s). "
                            "Dentro del criterio amplio."
                        ),
                    },
                    "motivo": "",
                }
            ],
        },
    }


def test_publicacion_muestra_formulario_y_encola(app, client, login, monkeypatch):
    job = _job()
    workspace = crear_workspace(job.id)
    canonical.escribir_registros(
        canonical.ruta_canonica(workspace, "eventquery"), [_referencia()]
    )
    carpeta = workspace / "resultados" / "indicios"
    carpeta.mkdir(parents=True, exist_ok=True)
    datos_cruce = _cruce()
    datos_cruce["huella"] = indicios._huella_atribuciones(workspace)
    (carpeta / "cruce_eventquery.json").write_text(
        json.dumps(datos_cruce), encoding="utf-8"
    )
    analista = User(username="tana", role="analista", analyst_code="tana")
    analista.set_password("secret")
    db.session.add(analista)
    db.session.commit()
    login()

    respuesta = client.get(f"/jobs/{job.id}/paneles/publicacion/127")
    assert respuesta.status_code == 200
    html = respuesta.get_data(as_text=True)
    assert "Revisión de publicación" in html
    assert "seiscomp:000280" in html
    assert "Solicitar revisión" in html

    estados = {}
    monkeypatch.setattr(
        review_reports,
        "guardar_estado",
        lambda clave, datos: estados.__setitem__(clave, dict(datos)),
    )
    monkeypatch.setattr(
        "tasks.reports.generar_informe_revision.delay",
        lambda report_id: None,
    )

    respuesta = client.post(
        f"/jobs/{job.id}/paneles/publicacion/127",
        data={
            "asignado": str(analista.id),
            "formato": "pdf",
            "nota": "Revisar la publicación",
        },
    )
    assert respuesta.status_code == 302
    estado = next(iter(estados.values()))
    assert estado["kind"] == "publicacion"
    assert estado["assigned_to_id"] == analista.id
    assert estado["fuente"] == "eventquery"
    fila = estado["filas"][0]
    assert fila["evento"] == "eventquery:000127"
    assert fila["kind"] == "publicacion"
    assert fila["cruce"]["candidato"]["evento_local"] == "seiscomp:000280"


def _evento_local() -> dict:
    return {
        "source_id": "seiscomp",
        "event_id": "seiscomp:000280",
        "source_event_id": "csn_prueba",
        "event_time": "2026-11-03 11:51:19",
        "latitude": -22.63,
        "longitude": -68.687,
        "depth_km": 82.9,
        "magnitude": 2.5,
        "magnitude_type": "MLv",
        "analyst": "tana",
        "raw_index": 280,
        "raw": {},
    }


def test_revision_local_muestra_formulario_y_encola(
    app, client, login, monkeypatch
):
    job = _job()
    workspace = crear_workspace(job.id)
    canonical.escribir_registros(
        canonical.ruta_canonica(workspace, "seiscomp"), [_evento_local()]
    )
    analista = User(username="tana2", role="analista", analyst_code="tana")
    analista.set_password("secret")
    db.session.add(analista)
    db.session.commit()
    login()

    respuesta = client.get(
        f"/jobs/{job.id}/paneles/revision-local",
        query_string={"fuente": "seiscomp", "evento": "seiscomp:000280"},
    )
    assert respuesta.status_code == 200
    html = respuesta.get_data(as_text=True)
    assert "Revisión de solución local" in html
    assert "seiscomp:000280" in html
    assert "tana2" in html

    estados = {}
    monkeypatch.setattr(
        review_reports,
        "guardar_estado",
        lambda clave, datos: estados.__setitem__(clave, dict(datos)),
    )
    monkeypatch.setattr(
        "tasks.reports.generar_informe_revision.delay",
        lambda report_id: None,
    )

    respuesta = client.post(
        f"/jobs/{job.id}/paneles/revision-local",
        data={
            "fuente": "seiscomp",
            "evento": "seiscomp:000280",
            "formato": "pdf",
            "nota": "Revisar",
        },
    )
    assert respuesta.status_code == 302
    estado = next(iter(estados.values()))
    assert estado["kind"] == "solucion"
    assert estado["assigned_to_id"] == analista.id
    assert estado["filas"][0]["evento"] == "seiscomp:000280"
    assert estado["filas"][0]["kind"] == "solucion"
