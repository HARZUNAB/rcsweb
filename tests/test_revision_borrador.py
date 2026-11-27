"""Pruebas del flujo de borrador de solicitudes de revisión."""

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
from app.services import review
from app.services.workspace import crear_workspace


def _usuarios():
    admin = User.query.filter_by(username="tester").one()
    analista = User(
        username="borrador-analista",
        role="analista",
        analyst_code="borrador",
        email="borrador@csn.uchile.cl",
    )
    analista.set_password("secret")
    db.session.add(analista)
    db.session.commit()
    return admin, analista


def _borrador(creado_por: User, asignado: User):
    job = Job(
        id=nuevo_uuid(),
        period_start=datetime(2026, 11, 1, tzinfo=UTC),
        period_end=datetime(2026, 11, 30, tzinfo=UTC),
        status="done",
    )
    db.session.add(job)
    db.session.flush()
    workspace = crear_workspace(job.id)
    carpeta = workspace / "revisiones"
    carpeta.mkdir(parents=True, exist_ok=True)
    reporte = carpeta / "borrador.pdf"
    reporte.write_bytes(b"%PDF-1.4 borrador")
    solicitud = ReviewRequest(
        job_id=job.id,
        source_id="seiscomp",
        created_by_id=creado_por.id,
        assigned_to_id=asignado.id,
        status="borrador",
        notified_at=utcnow(),
        report_path="revisiones/borrador.pdf",
        report_name="borrador.pdf",
        report_format="pdf",
        email_skipped=False,
    )
    db.session.add(solicitud)
    db.session.flush()
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
    return solicitud, reporte


def _entrar_como(client, username: str):
    client.post("/logout")
    respuesta = client.post(
        "/login",
        data={"username": username, "password": "secret"},
    )
    assert respuesta.status_code == 302


def test_analista_asignado_no_ve_el_borrador(app, client, login):
    admin, analista = _usuarios()
    solicitud, _reporte = _borrador(admin, analista)
    _entrar_como(client, "borrador-analista")

    detalle = client.get(f"/revisiones/{solicitud.id}")
    assert detalle.status_code == 403

    listado = client.get("/revisiones")
    assert listado.status_code == 200
    html = listado.get_data(as_text=True)
    assert f"/revisiones/{solicitud.id}" not in html


def test_creador_revisa_y_envia_borrador_sin_correo(app, client, login):
    admin, analista = _usuarios()
    solicitud, reporte = _borrador(admin, analista)
    login()

    detalle = client.get(f"/revisiones/{solicitud.id}")
    assert detalle.status_code == 200
    html = detalle.get_data(as_text=True)
    assert "Borrador pendiente de envío" in html
    assert "He revisado el PDF" in html
    assert "Enviar solicitud" in html
    assert "Descartar borrador" in html
    assert f'href="/revisiones/{solicitud.id}/pdf?inline=1"' in html

    respuesta = client.post(
        f"/revisiones/{solicitud.id}/enviar",
        data={"revisado": "1", "notificar": "0"},
    )
    assert respuesta.status_code == 302
    db.session.refresh(solicitud)
    assert solicitud.status == "notificada"
    assert solicitud.email_skipped is True
    assert solicitud.email_sent_at is None
    assert reporte.is_file()

    _entrar_como(client, "borrador-analista")
    detalle = client.get(f"/revisiones/{solicitud.id}")
    assert detalle.status_code == 200
    assert "Aceptar solicitud" in detalle.get_data(as_text=True)


def test_no_envia_sin_marcar_he_revisado_el_pdf(app, client, login):
    admin, analista = _usuarios()
    solicitud, _reporte = _borrador(admin, analista)
    login()

    respuesta = client.post(
        f"/revisiones/{solicitud.id}/enviar",
        data={"notificar": "0"},
        follow_redirects=True,
    )
    assert respuesta.status_code == 200
    assert "He revisado el PDF" in respuesta.get_data(as_text=True)
    db.session.refresh(solicitud)
    assert solicitud.status == "borrador"


def test_error_de_correo_mantiene_el_borrador(app, client, login):
    admin, analista = _usuarios()
    solicitud, _reporte = _borrador(admin, analista)
    login()
    app.config["MAIL_SUPPRESS_SEND"] = False

    respuesta = client.post(
        f"/revisiones/{solicitud.id}/enviar",
        data={
            "revisado": "1",
            "notificar": "1",
            "adjuntar_pdf": "1",
        },
        follow_redirects=True,
    )
    assert respuesta.status_code == 200
    assert "No se pudo enviar el correo" in respuesta.get_data(as_text=True)
    db.session.refresh(solicitud)
    assert solicitud.status == "borrador"
    assert solicitud.email_error
    assert solicitud.email_sent_at is None


def test_descartar_borrador_libera_los_eventos(app, client, login):
    admin, analista = _usuarios()
    solicitud, reporte = _borrador(admin, analista)
    login()
    request_id = solicitud.id
    job_id = solicitud.job_id

    assert review.conflictos(job_id, "seiscomp", ["seiscomp:000001"])

    respuesta = client.post(f"/revisiones/{request_id}/descartar")
    assert respuesta.status_code == 302
    assert respuesta.headers["Location"].endswith("/revisiones")

    assert db.session.get(ReviewRequest, request_id) is None
    assert not reporte.exists()
    assert review.conflictos(job_id, "seiscomp", ["seiscomp:000001"]) == []


def test_analista_no_puede_descartar_borrador_ajeno(app, client):
    admin, analista = _usuarios()
    otro = User(username="borrador-otro", role="analista")
    otro.set_password("secret")
    db.session.add(otro)
    db.session.commit()
    solicitud, _reporte = _borrador(admin, analista)
    _entrar_como(client, "borrador-otro")

    respuesta = client.post(f"/revisiones/{solicitud.id}/descartar")
    assert respuesta.status_code == 403
    assert db.session.get(ReviewRequest, solicitud.id) is not None
