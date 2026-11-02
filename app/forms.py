"""Formularios WTForms."""

from __future__ import annotations

import datetime
import os

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DateField,
    IntegerField,
    PasswordField,
    RadioField,
    SelectField,
    StringField,
    SubmitField,
)
from wtforms.validators import (
    DataRequired,
    EqualTo,
    Length,
    NumberRange,
    Optional,
    ValidationError,
)
from wtforms.widgets import TextInput

from .security import ETIQUETAS_ROL, ROLES_VALIDOS


class FechaField(DateField):
    """Fecha visible dd/mm/aaaa y compatible con ISO en posts viejos."""

    widget = TextInput()

    def __init__(self, label=None, validators=None, **kwargs):
        kwargs.setdefault("format", "%d/%m/%Y")
        super().__init__(label, validators, **kwargs)

    def process_formdata(self, valuelist):
        self._error_invalido = False
        if not valuelist:
            return
        texto = str(valuelist[0]).strip()
        if not texto:
            self.data = None
            return
        for formato in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%Y-%m-%d"):
            try:
                self.data = datetime.datetime.strptime(texto, formato).date()
                return
            except ValueError:
                continue
        self.data = None
        self._error_invalido = True

    def validate(self, form, extra_validators=()):
        if not self.raw_data or not str(self.raw_data[0]).strip():
            self.process_errors.append("Este campo es obligatorio.")
            self.errors = list(self.process_errors)
            return False
        if getattr(self, "_error_invalido", False):
            self.process_errors.append("Formato de fecha inválido. Use dd/mm/aaaa.")
            self.errors = list(self.process_errors)
            return False
        return super().validate(form, extra_validators)


def _ssh_host() -> str:
    return os.environ.get("CATALOGOS_SSH_HOST", "10.54.217.9")


def _ssh_user() -> str:
    return os.environ.get("CATALOGOS_SSH_USER", "sysopr")


def _radio_default() -> int:
    try:
        return max(1, int(os.environ.get("SEISCOMP_RADIO_KM", "400")))
    except ValueError:
        return 400


def _principal_incluida(form, seleccion: list[str]) -> bool:
    principal = form.primary_source.data
    if principal and principal not in seleccion:
        form.primary_source.errors.append(
            "La fuente principal debe estar entre las fuentes incluidas."
        )
        return False
    return True


class LoginForm(FlaskForm):
    username = StringField("Usuario", validators=[DataRequired(), Length(min=3, max=80)])
    password = PasswordField("Contraseña", validators=[DataRequired()])
    remember = BooleanField("Recordarme")
    submit = SubmitField("Entrar")


class PasswordChangeForm(FlaskForm):
    """Cambio de la contraseña del usuario conectado."""

    current_password = PasswordField(
        "Contraseña actual", validators=[DataRequired()]
    )
    new_password = PasswordField(
        "Nueva contraseña",
        validators=[DataRequired(), Length(min=8, max=128)],
    )
    confirm_password = PasswordField(
        "Repetir la nueva contraseña",
        validators=[
            DataRequired(),
            EqualTo("new_password", message="Las contraseñas nuevas no coinciden."),
        ],
    )
    submit = SubmitField("Cambiar contraseña")


class JobForm(FlaskForm):
    period_start = FechaField("Desde")
    period_end = FechaField("Hasta")
    primary_source = RadioField(
        "Fuente local principal",
        choices=[],
        validators=[DataRequired()],
    )
    submit = SubmitField("Validar y crear trabajo")


    def validate_period_end(self, field):  # noqa: N802 - API de WTForms
        if self.period_start.data and field.data and field.data < self.period_start.data:
            raise ValidationError("La fecha de término debe ser posterior a la de inicio.")


class SolicitudForm(FlaskForm):
    period_start = FechaField("Desde")
    period_end = FechaField("Hasta")
    server = StringField("Servidor", validators=[DataRequired()], default=_ssh_host)
    remote_user = StringField("Usuario", validators=[DataRequired()], default=_ssh_user)
    password = PasswordField("Contraseña del servidor", validators=[DataRequired()])
    radio_km = IntegerField(
        "Radio de estaciones (km)",
        default=_radio_default,
        validators=[
            Optional(),
            NumberRange(min=1, message="El radio debe ser mayor que cero."),
        ],
    )
    primary_source = RadioField(
        "Fuente local principal",
        choices=[],
        validators=[DataRequired()],
    )
    submit = SubmitField("Solicitar y descargar")

    def validate_period_end(self, field):  # noqa: N802 - API de WTForms
        if self.period_start.data and field.data and field.data < self.period_start.data:
            raise ValidationError("La fecha de término debe ser posterior a la de inicio.")


class ReintentarForm(FlaskForm):
    password = PasswordField("Contraseña del servidor", validators=[DataRequired()])
    submit = SubmitField("Reintentar descarga")


class UsuarioForm(FlaskForm):
    """Alta de un usuario desde la administración."""

    username = StringField(
        "Usuario", validators=[DataRequired(), Length(min=3, max=80)]
    )
    role = SelectField(
        "Rol",
        choices=[(rol, ETIQUETAS_ROL[rol]) for rol in ROLES_VALIDOS],
        default="analista",
    )
    password = PasswordField(
        "Contraseña",
        validators=[DataRequired(), Length(min=8, max=128)],
    )
    confirm_password = PasswordField(
        "Repetir contraseña",
        validators=[
            DataRequired(),
            EqualTo("password", message="Las contraseñas no coinciden."),
        ],
    )
    active = BooleanField("Activo", default=True)
    submit = SubmitField("Crear usuario")


class RolUsuarioForm(FlaskForm):
    """Cambio de rol y estado de un usuario."""

    role = SelectField(
        "Rol", choices=[(rol, ETIQUETAS_ROL[rol]) for rol in ROLES_VALIDOS]
    )
    active = BooleanField("Activo")
    submit = SubmitField("Guardar cambios")


class ResetPasswordForm(FlaskForm):
    """Restablecimiento de contraseña por un administrador."""

    new_password = PasswordField(
        "Nueva contraseña",
        validators=[DataRequired(), Length(min=8, max=128)],
    )
    confirm_password = PasswordField(
        "Repetir la nueva contraseña",
        validators=[
            DataRequired(),
            EqualTo("new_password", message="Las contraseñas no coinciden."),
        ],
    )
    submit = SubmitField("Restablecer contraseña")
