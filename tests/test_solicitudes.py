"""Pruebas de solicitudes SSH y creación del trabajo."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from types import SimpleNamespace

from app.extensions import db
from app.models import (
    AuditLog,
    CatalogRequest,
    CatalogRequestFile,
    Job,
    User,
    nuevo_uuid,
)
from app.services.acquisition import ejecutar_solicitud, preparar_workspace

SAMPLES = __import__("pathlib").Path(__file__).resolve().parent.parent / "samples"
INICIO = "20261001000000"
FIN = "20261031235959"


def _solicitud(app, status="queued"):
    solicitud = CatalogRequest(
        id=nuevo_uuid(),
        mode="ssh",
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 31, 23, 59, 59, tzinfo=UTC),
        status=status,
        server="10.54.217.9",
        remote_user="sysopr",
        requested_by_id=db.session.execute(
            db.select(User.id).filter_by(username="tester")
        ).scalar_one(),
    )
    db.session.add(solicitud)
    db.session.commit()
    db.session.add_all(
        [
            CatalogRequestFile(
                request_id=solicitud.id,
                kind="eventquery",
                format="eventquery",
                status="pending",
            ),
            CatalogRequestFile(
                request_id=solicitud.id,
                kind="seisan",
                format="seisan",
                status="pending",
            ),
        ]
    )
    db.session.commit()
    preparar_workspace(solicitud.id)
    return solicitud


def _traer_catalogos_falso(eventquery_valido=True):
    class Conexion:
        def __init__(self, password, log=None):
            self.password = password
            self.log = log

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def verificar_conexion(conexion, log=None, progreso=None):
        if progreso:
            progreso(1.0)

    def traer_seisan(inicio, fin, conexion, cwd=".", log=None, progreso=None, forzar=False):
        assert forzar is True
        destino = __import__("pathlib").Path(cwd) / f"select_{inicio}_{fin}.out"
        shutil.copy2(SAMPLES / "select.out", destino)
        if progreso:
            progreso(1.0)
        return str(destino)

    def traer_eventquery(inicio, fin, conexion, cwd=".", log=None, progreso=None, forzar=False):
        assert forzar is True
        destino = __import__("pathlib").Path(cwd) / f"eventquery_{inicio}_{fin}.csv"
        if eventquery_valido:
            shutil.copy2(
                SAMPLES / "eventquery_20261001000000_20261031235959.csv",
                destino,
            )
        else:
            destino.write_text("a,b\n1,2\n", encoding="utf-8")
        if progreso:
            progreso(1.0)
        return str(destino)

    return SimpleNamespace(
        IP_REMOTA="10.54.217.9",
        USUARIO_REMOTO="sysopr",
        Conexion=Conexion,
        verificar_conexion=verificar_conexion,
        traer_seisan=traer_seisan,
        traer_eventquery=traer_eventquery,
    )


def test_nueva_solicitud_encola(client, login, monkeypatch):
    login()
    llamadas = []
    monkeypatch.setattr(
        "app.blueprints.solicitudes.encolar_solicitud",
        lambda request_id, password: llamadas.append((request_id, password)),
    )

    respuesta = client.post(
        "/solicitudes/nueva",
        data={
            "period_start": "2026-10-01",
            "period_end": "2026-10-31",
            "server": "10.54.217.9",
            "remote_user": "sysopr",
            "password": "secreto",
        },
    )

    assert respuesta.status_code == 302
    solicitud = db.session.execute(db.select(CatalogRequest)).scalar_one()
    assert solicitud.status == "queued"
    assert solicitud.server == "10.54.217.9"
    assert solicitud.remote_user == "sysopr"
    assert {archivo.kind for archivo in solicitud.files} == {"eventquery", "seisan"}
    assert llamadas == [(solicitud.id, "secreto")]
    assert (
        db.session.execute(db.select(AuditLog).filter_by(action="catalog.request"))
        .scalar_one()
        .entity
        == solicitud.id
    )


def test_lista_y_detalle(client, login, app):
    login()
    solicitud = _solicitud(app)

    assert client.get("/solicitudes/").status_code == 200
    respuesta = client.get(f"/solicitudes/{solicitud.id}")
    assert respuesta.status_code == 200
    assert "10.54.217.9" in respuesta.get_data(as_text=True)


def test_ejecutar_solicitud_crea_job(app, monkeypatch):
    solicitud = _solicitud(app)
    encolados = []
    monkeypatch.setattr(
        "app.services.acquisition._cargar_traer_catalogos",
        lambda: _traer_catalogos_falso(True),
    )
    monkeypatch.setattr(
        "app.services.acquisition.encolar_trabajo",
        lambda job_id: encolados.append(job_id),
    )

    resultado = ejecutar_solicitud(solicitud.id, "secreto")

    assert resultado["estado"] == "done"
    db.session.expire_all()
    solicitud = db.session.get(CatalogRequest, solicitud.id)
    assert solicitud.status == "done"
    assert solicitud.progress == 100
    job = db.session.execute(db.select(Job)).scalar_one()
    assert job.origin == "ssh"
    assert job.catalog_request_id == solicitud.id
    assert {source.kind for source in job.sources} == {"eventquery", "seisan"}
    assert {archivo.kind for archivo in job.files} == {"eventquery", "seisan"}
    assert encolados == [job.id]


def test_ejecutar_solicitud_invalida_no_crea_job(app, monkeypatch):
    solicitud = _solicitud(app)
    monkeypatch.setattr(
        "app.services.acquisition._cargar_traer_catalogos",
        lambda: _traer_catalogos_falso(False),
    )
    monkeypatch.setattr("app.services.acquisition.encolar_trabajo", lambda _id: None)

    resultado = ejecutar_solicitud(solicitud.id, "secreto")

    assert resultado["estado"] == "failed"
    db.session.expire_all()
    solicitud = db.session.get(CatalogRequest, solicitud.id)
    assert solicitud.status == "failed"
    assert db.session.execute(db.select(Job)).scalar_one_or_none() is None


def test_reintentar_resetea_y_encola(client, login, app, monkeypatch):
    login()
    solicitud = _solicitud(app, status="failed")
    for archivo in solicitud.files:
        archivo.status = "error"
        archivo.message = "falló"
    db.session.commit()
    llamadas = []
    monkeypatch.setattr(
        "app.blueprints.solicitudes.encolar_solicitud",
        lambda request_id, password: llamadas.append((request_id, password)),
    )

    respuesta = client.post(
        f"/solicitudes/{solicitud.id}/reintentar",
        data={"password": "secreto"},
    )

    assert respuesta.status_code == 302
    db.session.expire_all()
    solicitud = db.session.get(CatalogRequest, solicitud.id)
    assert solicitud.status == "queued"
    assert all(archivo.status == "pending" for archivo in solicitud.files)
    assert llamadas == [(solicitud.id, "secreto")]


def test_reintentar_solo_creador_o_admin(client, app, monkeypatch):
    normal = User(username="normal", role="analista")
    normal.set_password("clave")
    db.session.add(normal)
    db.session.commit()
    solicitud = _solicitud(app, status="failed")
    monkeypatch.setattr("app.blueprints.solicitudes.encolar_solicitud", lambda *_: None)

    client.post("/login", data={"username": "normal", "password": "clave"})
    respuesta = client.post(f"/solicitudes/{solicitud.id}/reintentar", data={"password": "x"})

    assert respuesta.status_code == 403
