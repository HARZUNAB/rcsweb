"""Pruebas de la solicitud de revisión de un evento publicado."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from app.domain.catalogs import canonical
from app.extensions import db
from app.models import Job, User, nuevo_uuid
from app.services import indicios, review, review_reports
from app.services.workspace import crear_workspace


def test_notificar_desde_formulario_usa_valor_o_defecto():
    assert review.notificar_desde_formulario(None, True) is True
    assert review.notificar_desde_formulario("", False) is False
    assert review.notificar_desde_formulario("1", False) is True
    assert review.notificar_desde_formulario("0", True) is False


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
    assert "Agregar a la bandeja" in html
    assert "No enviar correo; crear la solicitud igualmente" in html
    assert 'id="publicacion-notificar-no"' in html
    assert 'id="publicacion-notificar-si"' in html

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
    assert estado["notificar"] is False
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
    assert "Agregar a la bandeja" in html
    assert "No enviar correo; crear la solicitud igualmente" in html
    assert 'id="revision-local-notificar-no"' in html
    assert 'id="revision-local-notificar-si"' in html

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
    assert estado["notificar"] is False
    assert estado["filas"][0]["evento"] == "seiscomp:000280"
    assert estado["filas"][0]["kind"] == "solucion"


class _FakeRedis:
    def __init__(self):
        self.datos = {}

    def get(self, clave):
        return self.datos.get(clave)

    def set(self, clave, valor, ex=None):
        self.datos[clave] = valor

    def delete(self, clave):
        self.datos.pop(clave, None)

    def expire(self, clave, ttl):
        return clave in self.datos

    def ttl(self, clave):
        return 43200


def test_bandeja_agrupa_por_responsable_y_envia(
    app, client, login, monkeypatch
):
    from app.services import review_drafts

    job = _job()
    admin = User.query.filter_by(username="tester").one()
    primero = User(username="uno", role="analista", analyst_code="uno")
    primero.set_password("secret")
    segundo = User(username="dos", role="analista", analyst_code="dos")
    segundo.set_password("secret")
    db.session.add_all([primero, segundo])
    db.session.commit()
    fake = _FakeRedis()
    monkeypatch.setattr(review_drafts, "_redis", lambda: fake)
    with app.app_context():
        for evento, asignado, kind in (
            ("seiscomp:000001", primero.id, "solucion"),
            ("eventquery:000001", primero.id, "publicacion"),
            ("seiscomp:000002", segundo.id, "solucion"),
        ):
            review_drafts.agregar(
                job.id,
                admin.id,
                {
                    "fila": {
                        "fuente": (
                            "eventquery"
                            if kind == "publicacion"
                            else "seiscomp"
                        ),
                        "evento": evento,
                        "fecha_hora": "2026-11-03 11:51:23",
                        "analista": "ana",
                    },
                    "assigned_to_id": asignado,
                    "kind": kind,
                },
            )
    login()

    pagina = client.get(f"/jobs/{job.id}/paneles/bandeja")
    assert pagina.status_code == 200
    html = pagina.get_data(as_text=True)
    assert "Bandeja de revisión" in html
    assert "uno" in html and "dos" in html
    assert "3 eventos" in html
    assert html.count('<form method="post"') == html.count(
        'name="csrf_token"'
    )
    assert "No enviar correos; crear las solicitudes igualmente" in html
    assert 'id="bandeja-notificar-no"' in html
    assert 'id="bandeja-notificar-si"' in html

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
        f"/jobs/{job.id}/paneles/bandeja/enviar",
        data={"formato": "pdf", "nota": "Revisar"},
    )
    assert respuesta.status_code == 302
    assert len(estados) == 2
    por_asignado = {estado["assigned_to_id"]: estado for estado in estados.values()}
    assert all(estado["notificar"] is False for estado in estados.values())
    assert len(por_asignado[primero.id]["filas"]) == 2
    assert por_asignado[primero.id]["kind"] == "mixta"
    assert len(por_asignado[segundo.id]["filas"]) == 1
    assert por_asignado[segundo.id]["kind"] == "solucion"
    with app.app_context():
        items = review_drafts.listar(job.id, admin.id)
        assert len(items) == 3
        assert all(item.get("estado") == "enviando" for item in items)
        for report_id in estados:
            review_drafts.quitar_enviados(job.id, admin.id, report_id)
        assert review_drafts.listar(job.id, admin.id) == []
