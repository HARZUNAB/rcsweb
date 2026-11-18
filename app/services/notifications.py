"""Notificaciones por correo de las solicitudes de revisión."""

from __future__ import annotations

import html
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from flask import current_app

from ..extensions import db
from ..models import ReviewRequest, utcnow
from .workspace import ruta_workspace

log = logging.getLogger(__name__)


def _texto(valor) -> str:
    return "" if valor is None else str(valor).strip()


def _firma(config) -> list[str]:
    return [
        linea.strip()
        for linea in _texto(config.get("MAIL_SIGNATURE")).split("|")
        if linea.strip()
    ]


def _base_url(base_url: str = "") -> str:
    base = _texto(base_url) or _texto(current_app.config.get("RCS_PUBLIC_URL"))
    return base.rstrip("/")


def enlace_solicitud(solicitud: ReviewRequest, base_url: str = "") -> str:
    ruta = f"/revisiones/{solicitud.id}"
    base = _base_url(base_url)
    return f"{base}{ruta}" if base else ruta


def construir_mensaje(
    solicitud: ReviewRequest, base_url: str = ""
) -> EmailMessage:
    config = current_app.config
    analista = solicitud.assigned_to
    destinatario = _texto(getattr(analista, "email", ""))
    remitente = (
        _texto(config.get("MAIL_DEFAULT_SENDER")) or "rcsweb@localhost"
    )
    nombre = _texto(config.get("MAIL_FROM_NAME"))
    enlace = enlace_solicitud(solicitud, base_url)
    cantidad = len(solicitud.events or [])
    saludo = _texto(getattr(analista, "username", "")) or "analista"
    firma = _firma(config)

    asunto = f"[RCS Web] Nueva solicitud de revisión #{solicitud.id}"
    cuerpo = "\n".join(
        [
            f"Hola {saludo},",
            "",
            (
                f"Se le asignó la solicitud de revisión #{solicitud.id} "
                f"con {cantidad} evento"
                f"{'' if cantidad == 1 else 's'} del trabajo "
                f"{solicitud.job_id} ({solicitud.source_id})."
            ),
            "",
            (
                "Ingrese a la plataforma para informarse de la solicitud "
                "y aceptarla:"
            ),
            enlace,
            "",
            (
                "Al aceptarla, la solicitud quedará En proceso. Cuando "
                "termine, use «Cerrar solicitud», describa lo realizado y, "
                "si corresponde, adjunte la evidencia y la URL actualizada "
                "de cada evento que haya cambiado sus parámetros."
            ),
            "",
            *firma,
        ]
    )

    firma_html = "<br>".join(html.escape(linea) for linea in firma)
    cuerpo_html = (
        f"<p>Hola {html.escape(saludo)},</p>"
        f"<p>Se le asignó la solicitud de revisión "
        f"<strong>#{solicitud.id}</strong> con "
        f"<strong>{cantidad}</strong> evento"
        f"{'' if cantidad == 1 else 's'} del trabajo "
        f"<code>{html.escape(solicitud.job_id)}</code> "
        f"({html.escape(solicitud.source_id)}).</p>"
        f"<p>Ingrese a la plataforma para informarse de la solicitud y "
        f"aceptarla:</p>"
        f"<p><a href=\"{html.escape(enlace)}\">{html.escape(enlace)}</a></p>"
        f"<p>Al aceptarla, la solicitud quedará <strong>En proceso</strong>. "
        f"Cuando termine, use «Cerrar solicitud», describa lo realizado y, "
        f"si corresponde, adjunte la evidencia y la URL actualizada de cada "
        f"evento que haya cambiado sus parámetros.</p>"
        f"<p>{firma_html}</p>"
    )

    mensaje = EmailMessage()
    mensaje["Subject"] = asunto
    mensaje["From"] = (
        formataddr((nombre, remitente)) if nombre else remitente
    )
    mensaje["To"] = destinatario
    mensaje["Date"] = formatdate(localtime=True)
    dominio = remitente.split("@")[-1] if "@" in remitente else None
    mensaje["Message-ID"] = make_msgid(domain=dominio)
    mensaje.set_content(cuerpo)
    mensaje.add_alternative(cuerpo_html, subtype="html")
    return mensaje


def _guardar_eml(solicitud: ReviewRequest, mensaje: EmailMessage):
    carpeta = ruta_workspace(solicitud.job_id) / "revisiones"
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"correo_{solicitud.id}.eml"
    ruta.write_bytes(mensaje.as_bytes())
    return ruta


def _enviar(mensaje: EmailMessage, config) -> None:
    host = _texto(config.get("MAIL_SERVER"))
    puerto = int(config.get("MAIL_PORT") or 25)
    timeout = int(config.get("MAIL_TIMEOUT") or 10)
    usuario = _texto(config.get("MAIL_USERNAME"))
    password = config.get("MAIL_PASSWORD") or ""
    contexto = ssl.create_default_context()

    if config.get("MAIL_USE_SSL"):
        cliente = smtplib.SMTP_SSL(
            host, puerto, context=contexto, timeout=timeout
        )
    else:
        cliente = smtplib.SMTP(host, puerto, timeout=timeout)
    with cliente:
        cliente.ehlo()
        if config.get("MAIL_USE_TLS") and not config.get("MAIL_USE_SSL"):
            cliente.starttls(context=contexto)
            cliente.ehlo()
        if usuario:
            cliente.login(usuario, password)
        cliente.send_message(mensaje)


def enviar_solicitud(
    solicitud: ReviewRequest, base_url: str = ""
) -> bool:
    """Envía el aviso al analista asignado.

    Nunca propaga errores de SMTP: deja el detalle en ``email_error`` para que
    la solicitud siga visible y el creador pueda corregir la configuración.
    """
    if solicitud.email_sent_at is not None:
        return True

    analista = solicitud.assigned_to
    destinatario = _texto(getattr(analista, "email", ""))
    solicitud.email_to = destinatario or None
    if analista is None:
        solicitud.email_error = "La solicitud no tiene analista asignado."
        db.session.commit()
        return False
    if not destinatario:
        solicitud.email_error = (
            "El analista no tiene correo electrónico configurado."
        )
        db.session.commit()
        return False

    try:
        mensaje = construir_mensaje(solicitud, base_url)
    except Exception as exc:  # noqa: BLE001 - se informa en el detalle
        solicitud.email_error = (
            f"No se pudo preparar el correo: {exc}"
        )[:500]
        db.session.commit()
        log.exception("No se pudo preparar el correo %s", solicitud.id)
        return False

    config = current_app.config
    if config.get("MAIL_SUPPRESS_SEND"):
        try:
            ruta = _guardar_eml(solicitud, mensaje)
        except Exception as exc:  # noqa: BLE001
            solicitud.email_error = (
                f"No se pudo guardar el correo de prueba: {exc}"
            )[:500]
            db.session.commit()
            log.exception("No se pudo guardar el correo %s", solicitud.id)
            return False
        solicitud.email_sent_at = utcnow()
        solicitud.email_error = None
        db.session.commit()
        log.info("Correo suprimido; guardado en %s", ruta)
        return True

    if not _texto(config.get("MAIL_SERVER")):
        solicitud.email_error = "SMTP no configurado (MAIL_SERVER vacío)."
        db.session.commit()
        return False

    try:
        _enviar(mensaje, config)
    except Exception as exc:  # noqa: BLE001 - se informa en el detalle
        solicitud.email_error = f"{type(exc).__name__}: {exc}"[:500]
        db.session.commit()
        log.exception("Error al enviar el correo %s", solicitud.id)
        return False

    solicitud.email_sent_at = utcnow()
    solicitud.email_error = None
    db.session.commit()
    return True
