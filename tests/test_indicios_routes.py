"""Pruebas de las rutas de indicios y de la solicitud de revisión."""

from __future__ import annotations

import json

from app.domain.catalogs import canonical
from app.extensions import db
from app.models import EventReviewRequest, Job, JobSource, User, nuevo_uuid
from app.services import indicios
from app.services.workspace import crear_workspace


def _evento(
    analyst: str,
    *,
    event_id: str,
    source_event_id: str,
    raw_index: int = 2650,
) -> dict:
    return {
        "source_id": "seiscomp",
        "event_id": event_id,
        "source_event_id": source_event_id,
        "event_time": "2026-10-28 15:23:36",
        "latitude": -52.857,
        "longitude": -71.570,
        "depth_km": 10.0,
        "magnitude": 3.0,
        "analyst": analyst,
        "raw_index": raw_index,
        "raw": {},
    }


def _arribo(event_id: str, estacion: str, lat: float, lon: float, pick: str, residual: float) -> dict:
    return {
        "source_id": "seiscomp",
        "event_id": event_id,
        "network": "C1",
        "station": estacion,
        "phase": "P",
        "pick_time": pick,
        "residual": residual,
        "weight": 1.0,
        "is_used_in_solution": True,
        "azimuth": 180.0,
        "station_latitude": lat,
        "station_longitude": lon,
        "raw": {},
    }


def _preparar(app, admin: User):
    job = Job(
        id=nuevo_uuid(),
        status="done",
        period_start=None,
        period_end=None,
        created_by_id=admin.id,
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
            capabilities=["eventos", "arribos", "inventario"],
        )
    )
    db.session.commit()
    workspace = crear_workspace(job.id)
    eventos = [
        _evento(
            "mdur",
            event_id="seiscomp:000001",
            source_event_id="csn_sc62026vdkls",
            raw_index=0,
        ),
        _evento(
            "otro",
            event_id="seiscomp:000002",
            source_event_id="csn_otro",
            raw_index=1,
        ),
    ]
    arribos = [
        _arribo("seiscomp:000001", "MG04", -52.857232, -71.569992, "2026-10-28 15:27:41.921878", 244.2),
        _arribo("seiscomp:000001", "MG03", -51.67, -71.57, "2026-10-28 15:27:41.512964", 223.47),
        _arribo("seiscomp:000001", "MG02", -51.43, -71.57, "2026-10-28 15:27:44.457146", 222.98),
        _arribo("seiscomp:000001", "USHA", -50.15, -71.57, "2026-10-28 15:27:43.230404", 203.63),
        _arribo("seiscomp:000001", "AY05", -45.0, -71.57, "2026-10-28 15:27:42.576141", 132.89),
        _arribo("seiscomp:000002", "OTRA", 0.5, 0.0, "2026-10-28 15:23:41", 200.0),
    ]
    canonical.escribir_registros(canonical.ruta_canonica(workspace, "seiscomp"), eventos)
    canonical.escribir_registros(canonical.ruta_arribos(workspace, "seiscomp"), arribos)
    indicios.generar_indicios(workspace, ["seiscomp"], job_id=job.id)
    return job


def test_lista_y_detalle_de_indicios(app, client, login):
    admin = User.query.filter_by(username="tester").first()
    job = _preparar(app, admin)
    login()

    listado = client.get(f"/jobs/{job.id}/indicios?fuente=seiscomp&alcance=todos")
    assert listado.status_code == 200
    html = listado.get_data(as_text=True)
    assert "Indicios de fases" in html
    assert "csn_sc62026vdkls" in html
    assert "Revisión prioritaria" in html

    detalle = client.get(f"/jobs/{job.id}/indicios/seiscomp/seiscomp:000001")
    assert detalle.status_code == 200
    html = detalle.get_data(as_text=True)
    assert "Evidencia" in html
    assert "244.2" in html
    assert "Pedir revisión" in html


def test_solicitar_revision_crea_registro(app, client, login):
    admin = User.query.filter_by(username="tester").first()
    job = _preparar(app, admin)
    login()

    respuesta = client.post(
        f"/jobs/{job.id}/indicios/revision",
        data={
            "fuente": "seiscomp",
            "evento": "seiscomp:000001",
            "id_evento_fuente": "csn_sc62026vdkls",
            "nota": "Revisar la asociación de las P.",
            "volver": f"/jobs/{job.id}/indicios?fuente=seiscomp",
        },
    )
    assert respuesta.status_code == 302
    solicitud = EventReviewRequest.query.filter_by(
        job_id=job.id, source_id="seiscomp", event_id="seiscomp:000001"
    ).first()
    assert solicitud is not None
    assert solicitud.note == "Revisar la asociación de las P."
    assert solicitud.requested_by_id == admin.id


def test_analista_ve_solo_sus_eventos_y_no_puede_pedir_revision(app, client):
    admin = User.query.filter_by(username="tester").first()
    job = _preparar(app, admin)

    analista = User(username="analista", role="analista", analyst_code="mdur")
    analista.set_password("secret")
    db.session.add(analista)
    db.session.flush()
    job.created_by_id = analista.id
    db.session.commit()

    client.post("/login", data={"username": "analista", "password": "secret"})

    listado = client.get(f"/jobs/{job.id}/indicios?fuente=seiscomp&alcance=todos")
    assert listado.status_code == 200
    html = listado.get_data(as_text=True)
    assert "csn_sc62026vdkls" in html
    assert "csn_otro" not in html
    assert "Pedir revisión" not in html

    propio = client.get(f"/jobs/{job.id}/indicios/seiscomp/seiscomp:000001")
    assert propio.status_code == 200
    ajeno = client.get(f"/jobs/{job.id}/indicios/seiscomp/seiscomp:000002")
    assert ajeno.status_code == 403

    respuesta = client.post(
        f"/jobs/{job.id}/indicios/revision",
        data={"fuente": "seiscomp", "evento": "seiscomp:000001"},
    )
    assert respuesta.status_code == 403


def test_listado_y_detalle_reutilizan_la_clasificacion_sospechoso(
    app, client, login, monkeypatch
):
    admin = User.query.filter_by(username="tester").first()
    job = _preparar(app, admin)
    workspace = crear_workspace(job.id)
    (workspace / "datos").mkdir(exist_ok=True)
    (workspace / "resultados").mkdir(exist_ok=True)
    (workspace / "datos" / "seiscomp_parametros.csv").write_text(
        ",Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista\n"
        "0,2026-10-28 15:23:36,-52.857,-71.570,10.0,3.0,M,mdur\n"
        "1,2026-10-28 15:23:36,-52.857,-71.570,10.0,3.0,M,otro\n",
        encoding="utf-8",
    )
    (workspace / "resultados" / "indice.json").write_text(
        json.dumps(
            {
                "catalogos": {
                    "seiscomp": {
                        "archivo": "datos/seiscomp_parametros.csv",
                        "filas": 2,
                        "columnas": [
                            "",
                            "Fecha_Hora",
                            "Latitud",
                            "Longitud",
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    def _clasificar(*_args, **_kwargs):
        return (
            [
                {
                    "sospechoso": True,
                    "residuo_km": 39.4,
                    "perp_km": 34.6,
                    "along_km": 250.0,
                }
            ],
            {"id": "perfil-prueba"},
        )

    monkeypatch.setattr(
        "app.blueprints.results.clasificar_eventos", _clasificar
    )
    login()

    listado = client.get(
        f"/jobs/{job.id}/indicios?fuente=seiscomp&alcance=todos"
    )
    html = listado.get_data(as_text=True)
    assert "Sospechosa" in html
    assert "residuo 39.4 km" in html

    detalle = client.get(
        f"/jobs/{job.id}/indicios/seiscomp/seiscomp:000001"
    )
    html = detalle.get_data(as_text=True)
    assert "sospechosa" in html
    assert "residuo al slab 39.4 km" in html
