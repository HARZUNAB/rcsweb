"""Pruebas del correo de notificación de solicitudes de revisión."""

from __future__ import annotations

from email import message_from_bytes, policy

from app.extensions import db
from app.models import (
    Job,
    ReviewRequest,
    ReviewRequestEvent,
    User,
    nuevo_uuid,
    utcnow,
)
from app.services import notifications
from app.services.workspace import crear_workspace


def _solicitud(email: str | None = "analista@csn.uchile.cl"):
    admin = User.query.filter_by(username="tester").first()
    analista = User(
        username="correo",
        role="analista",
        analyst_code="correo",
        email=email,
    )
    analista.set_password("secret")
    db.session.add(analista)
    db.session.flush()
    job = Job(
        id=nuevo_uuid(),
        status="done",
        period_start=None,
        period_end=None,
        created_by_id=admin.id,
    )
    db.session.add(job)
    db.session.flush()
    workspace = crear_workspace(job.id)
    carpeta = workspace / "revisiones"
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "informe.pdf").write_bytes(b"%PDF-1.4\nprueba\n")
    solicitud = ReviewRequest(
        job_id=job.id,
        source_id="seiscomp",
        created_by_id=admin.id,
        assigned_to_id=analista.id,
        status="notificada",
        notified_at=utcnow(),
        report_format="pdf",
        report_path="revisiones/informe.pdf",
        report_name="informe.pdf",
        email_attach_report=True,
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
            event_time="2026-11-06 07:23:35",
            magnitude=3.6,
        )
    )
    db.session.commit()
    return solicitud


def test_correo_suprimido_guarda_eml_y_marca_enviado(app):
    solicitud = _solicitud()
    assert notifications.enviar_solicitud(
        solicitud, base_url="http://localhost:8000"
    )

    db.session.refresh(solicitud)
    assert solicitud.email_sent_at is not None
    assert solicitud.email_to == "analista@csn.uchile.cl"
    assert solicitud.email_error is None

    ruta = (
        app.config["WORKSPACE_ROOT"]
        / solicitud.job_id
        / "revisiones"
        / f"correo_{solicitud.id}.eml"
    )
    assert ruta.is_file()
    mensaje = message_from_bytes(ruta.read_bytes(), policy=policy.default)
    cuerpo = mensaje.get_body(preferencelist=("plain",)).get_content()
    assert "Le solicito revisar la solicitud de revisión" in cuerpo
    assert "Comentarios de la solicitud" in cuerpo
    assert "Los antecedentes de cada revisión están en el PDF adjunto." in cuerpo
    assert "http://localhost:8000/revisiones/" not in cuerpo
    adjuntos = list(mensaje.iter_attachments())
    assert len(adjuntos) == 1
    assert adjuntos[0].get_filename() == "informe.pdf"


def test_correo_incluye_copias_sin_duplicar(app):
    solicitud = _solicitud()
    solicitud.email_cc = (
        "copia1@csn.uchile.cl, analista@csn.uchile.cl, "
        "copia2@csn.uchile.cl, copia1@csn.uchile.cl"
    )
    db.session.commit()

    mensaje = notifications.construir_mensaje(
        solicitud, base_url="http://localhost:8000"
    )
    assert mensaje["Cc"] == "copia1@csn.uchile.cl, copia2@csn.uchile.cl"


def test_correo_exige_adjunto_en_modo_correo(app):
    solicitud = _solicitud()
    solicitud.email_attach_report = False
    db.session.commit()

    assert not notifications.enviar_solicitud(solicitud)
    db.session.refresh(solicitud)
    assert "adjuntar el PDF" in solicitud.email_error


def test_correo_modo_plataforma_conserva_enlace(app):
    solicitud = _solicitud()
    solicitud.email_attach_report = False
    db.session.commit()
    app.config["RCS_NOTIFICACION_MODO"] = "plataforma"

    assert notifications.enviar_solicitud(
        solicitud, base_url="http://localhost:8000"
    )
    ruta = (
        app.config["WORKSPACE_ROOT"]
        / solicitud.job_id
        / "revisiones"
        / f"correo_{solicitud.id}.eml"
    )
    mensaje = message_from_bytes(ruta.read_bytes(), policy=policy.default)
    cuerpo = mensaje.get_body(preferencelist=("plain",)).get_content()
    assert "http://localhost:8000/revisiones/" in cuerpo
    assert "Se le asignó la solicitud de revisión" in cuerpo


def test_correo_sin_destinatario_deja_error(app):
    solicitud = _solicitud(email=None)
    assert not notifications.enviar_solicitud(solicitud)
    db.session.refresh(solicitud)
    assert solicitud.email_sent_at is None
    assert "no tiene correo" in solicitud.email_error


def test_correo_no_se_reenvia_si_ya_fue_enviado(app):
    solicitud = _solicitud()
    solicitud.email_sent_at = utcnow()
    db.session.commit()

    original = notifications._enviar
    llamado = {"veces": 0}

    def _no_enviar(*_args, **_kwargs):
        llamado["veces"] += 1

    notifications._enviar = _no_enviar
    try:
        assert notifications.enviar_solicitud(solicitud)
    finally:
        notifications._enviar = original
    assert llamado["veces"] == 0


def test_correo_registra_error_de_smtp(app, monkeypatch):
    solicitud = _solicitud()
    app.config["MAIL_SUPPRESS_SEND"] = False
    app.config["MAIL_SERVER"] = "smtp.test"

    def _fallar(*_args, **_kwargs):
        raise OSError("sin conexión")

    monkeypatch.setattr(notifications, "_enviar", _fallar)
    assert not notifications.enviar_solicitud(solicitud)
    db.session.refresh(solicitud)
    assert solicitud.email_sent_at is None
    assert "OSError" in solicitud.email_error
    assert "sin conexión" in solicitud.email_error


def test_correo_exitoso_marca_enviado(app, monkeypatch):
    solicitud = _solicitud()
    app.config["MAIL_SUPPRESS_SEND"] = False
    app.config["MAIL_SERVER"] = "smtp.test"
    enviados = []
    monkeypatch.setattr(
        notifications, "_enviar", lambda mensaje, config: enviados.append(mensaje)
    )

    assert notifications.enviar_solicitud(solicitud)
    db.session.refresh(solicitud)
    assert solicitud.email_sent_at is not None
    assert solicitud.email_error is None
    assert len(enviados) == 1
    assert enviados[0]["To"] == "analista@csn.uchile.cl"
