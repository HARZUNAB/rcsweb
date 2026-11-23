"""Pruebas de eliminación de solicitudes de revisión."""

from __future__ import annotations

from datetime import UTC, datetime

from app.extensions import db
from app.models import (
    Job,
    ReviewRequest,
    ReviewRequestEvent,
    User,
    nuevo_uuid,
    utcnow,
)
from app.services.workspace import crear_workspace


def _solicitud(creado_por: User):
    job = Job(
        id=nuevo_uuid(),
        period_start=datetime(2026, 11, 1, tzinfo=UTC),
        period_end=datetime(2026, 11, 30, tzinfo=UTC),
        status="done",
    )
    analista = User(username="eliminar-analista", role="analista")
    analista.set_password("secret")
    db.session.add_all([job, analista])
    db.session.commit()

    workspace = crear_workspace(job.id)
    carpeta = workspace / "revisiones"
    carpeta.mkdir(parents=True, exist_ok=True)
    reporte = carpeta / "informe.pdf"
    reporte.write_bytes(b"%PDF-1.4 prueba")

    solicitud = ReviewRequest(
        job_id=job.id,
        source_id="seiscomp",
        created_by_id=creado_por.id,
        assigned_to_id=analista.id,
        status="notificada",
        notified_at=utcnow(),
        report_path="revisiones/informe.pdf",
        report_name="informe.pdf",
        report_format="pdf",
    )
    db.session.add(solicitud)
    db.session.flush()
    evidencia = (
        workspace / "revisiones" / "evidencia" / str(solicitud.id) / "evidencia.pdf"
    )
    evidencia.parent.mkdir(parents=True, exist_ok=True)
    evidencia.write_bytes(b"%PDF-1.4 evidencia")
    solicitud.evidence_path = str(evidencia.relative_to(workspace))
    solicitud.evidence_name = "evidencia.pdf"
    db.session.add(
        ReviewRequestEvent(
            request_id=solicitud.id,
            source_id="seiscomp",
            event_id="seiscomp:000001",
            source_event_id="csn_prueba",
            fila_catalogo=0,
            event_time="2026-11-01 00:00:00",
        )
    )
    db.session.commit()
    return solicitud.id, reporte, evidencia


def _entrar_como(client, username: str):
    """Cambia de identidad con el flujo real de login.

    No se usa ``session_transaction`` porque el fixture mantiene un contexto
    de aplicación activo y Flask-Login cachea el usuario en ``g._login_user``.
    """
    client.post("/logout")
    respuesta = client.post(
        "/login",
        data={"username": username, "password": "secret"},
    )
    assert respuesta.status_code == 302


def test_admin_elimina_solicitud_y_archivos(app, client, login):
    admin = User.query.filter_by(username="tester").one()
    login()
    request_id, reporte, evidencia = _solicitud(admin)

    respuesta = client.post(f"/revisiones/{request_id}/eliminar")

    assert respuesta.status_code == 302
    assert respuesta.headers["Location"].endswith("/revisiones")
    with app.app_context():
        assert db.session.get(ReviewRequest, request_id) is None
        assert (
            ReviewRequestEvent.query.filter_by(request_id=request_id).count()
            == 0
        )
    assert not reporte.exists()
    assert not evidencia.exists()


def test_supervisor_no_puede_eliminar(app, client):
    admin = User.query.filter_by(username="tester").one()
    supervisor = User(username="eliminar-supervisor", role="supervisor")
    supervisor.set_password("secret")
    db.session.add(supervisor)
    db.session.commit()
    request_id, _reporte, _evidencia = _solicitud(admin)
    _entrar_como(client, "eliminar-supervisor")

    respuesta = client.post(f"/revisiones/{request_id}/eliminar")

    assert respuesta.status_code == 403
    with app.app_context():
        assert db.session.get(ReviewRequest, request_id) is not None


def test_analista_no_puede_eliminar(app, client):
    admin = User.query.filter_by(username="tester").one()
    analista = User(username="eliminar-otro", role="analista")
    analista.set_password("secret")
    db.session.add(analista)
    db.session.commit()
    request_id, _reporte, _evidencia = _solicitud(admin)
    _entrar_como(client, "eliminar-otro")

    respuesta = client.post(f"/revisiones/{request_id}/eliminar")

    assert respuesta.status_code == 403


def test_detalle_muestra_eliminar_solo_admin(app, client, login):
    admin = User.query.filter_by(username="tester").one()
    supervisor = User(username="eliminar-supervisor-2", role="supervisor")
    supervisor.set_password("secret")
    db.session.add(supervisor)
    db.session.commit()
    login()
    request_id, _reporte, _evidencia = _solicitud(admin)

    html = client.get(f"/revisiones/{request_id}").get_data(as_text=True)
    assert "Eliminar solicitud" in html
    modal = html[html.index("modalEliminarRevision") :]
    assert 'name="csrf_token"' in modal

    _entrar_como(client, "eliminar-supervisor-2")
    html = client.get(f"/revisiones/{request_id}").get_data(as_text=True)
    assert "Eliminar solicitud" not in html


def test_eliminar_solicitud_inexistente(client, login):
    login()

    respuesta = client.post("/revisiones/99999/eliminar")

    assert respuesta.status_code == 404
