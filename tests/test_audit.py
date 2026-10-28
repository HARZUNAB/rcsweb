"""Pruebas de auditoría y permisos de administración."""

from __future__ import annotations

from datetime import UTC, datetime

from app.extensions import db
from app.models import AuditLog, Job, JobArtifact, User, nuevo_uuid
from app.services.workspace import crear_workspace


def _acciones():
    return [
        registro.action
        for registro in db.session.execute(db.select(AuditLog).order_by(AuditLog.id))
        .scalars()
        .all()
    ]


def _login(client, username="tester", password="secret", follow=True):
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=follow,
    )


def test_login_fallido_y_correcto_quedan_registrados(client):
    client.post("/login", data={"username": "tester", "password": "mala"})
    client.post("/login", data={"username": "tester", "password": "secret"})
    client.post("/logout")

    acciones = _acciones()
    assert "auth.login_fail" in acciones
    assert "auth.login_ok" in acciones
    assert "auth.logout" in acciones


def test_alta_de_trabajo_queda_registrada(client, samples, sin_celery):
    _login(client)
    datos = {
        "period_start": "2026-10-01",
        "period_end": "2026-10-31",
        "seisan": (open(samples / "select.out", "rb"), "select.out"),
        "eventquery": (
            open(samples / "eventquery_20261001000000_20261031235959.csv", "rb"),
            "eventquery.csv",
        ),
    }
    client.post("/jobs/new", data=datos, content_type="multipart/form-data")

    registro = db.session.execute(db.select(AuditLog).filter_by(action="job.create")).scalar_one()
    assert registro.entity
    assert registro.meta["inicio"] == "20261001000000"
    assert len(registro.meta["archivos"]) == 2


def test_cancelacion_queda_registrada(client):
    _login(client)
    job = Job(
        id=nuevo_uuid(),
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 31, tzinfo=UTC),
        status="queued",
    )
    db.session.add(job)
    db.session.commit()

    client.post(f"/jobs/{job.id}/cancelar")

    registro = db.session.execute(db.select(AuditLog).filter_by(action="job.cancel")).scalar_one()
    assert registro.entity == job.id


def test_descarga_queda_registrada(client, login):
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
    (workspace / "resultados" / "demo.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    artefacto = JobArtifact(job_id=job.id, tipo="resultado", ruta="resultados/demo.csv", size=8)
    db.session.add(artefacto)
    db.session.commit()

    respuesta = client.get(f"/jobs/{job.id}/descargar/{artefacto.id}")

    assert respuesta.status_code == 200
    registro = db.session.execute(db.select(AuditLog).filter_by(action="download")).scalar_one()
    assert registro.entity == "resultados/demo.csv"


def test_admin_ve_auditoria_y_usuario_normal_recibe_403(client):
    _login(client)
    respuesta = client.get("/admin/auditoria")
    assert respuesta.status_code == 200
    assert "Auditoría" in respuesta.get_data(as_text=True)

    normal = User(username="normal", role="analista")
    normal.set_password("clave")
    db.session.add(normal)
    db.session.commit()
    client.post("/logout")
    _login(client, username="normal", password="clave")

    respuesta = client.get("/admin/auditoria")
    assert respuesta.status_code == 403
