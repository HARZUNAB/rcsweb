"""Formularios WTForms."""

from __future__ import annotations

import os

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import (
    BooleanField,
    DateField,
    IntegerField,
    PasswordField,
    RadioField,
    StringField,
    SubmitField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional, ValidationError

from .services.sources import default_primary, fuentes_locales

LOCALES = [(fuente.codigo, fuente.etiqueta) for fuente in fuentes_locales()]


def _ssh_host() -> str:
    return os.environ.get("CATALOGOS_SSH_HOST", "10.54.217.9")


def _ssh_user() -> str:
    return os.environ.get("CATALOGOS_SSH_USER", "sysopr")


def _radio_default() -> int:
    try:
        return max(1, int(os.environ.get("SEISCOMP_RADIO_KM", "400")))
    except ValueError:
        return 400


class LoginForm(FlaskForm):
    username = StringField("Usuario", validators=[DataRequired(), Length(min=3, max=80)])
    password = PasswordField("Contraseña", validators=[DataRequired()])
    remember = BooleanField("Recordarme")
    submit = SubmitField("Entrar")


class JobForm(FlaskForm):
    period_start = DateField("Desde", validators=[DataRequired()])
    period_end = DateField("Hasta", validators=[DataRequired()])

    eventquery = FileField(
        "Catálogo eventquery (CSV)",
        validators=[FileRequired(), FileAllowed(["csv"], "un CSV de eventquery")],
    )

    incluir_seiscomp = BooleanField("Incluir SeisComp", default=False)
    alias_seiscomp = StringField("Nombre de la fuente", validators=[Length(max=80)])
    seiscomp = FileField(
        "Exportación de SeisComp (CSV)",
        validators=[FileAllowed(["csv"], "un CSV de SeisComp")],
    )

    incluir_seisan = BooleanField("Incluir Seisan", default=False)
    alias_seisan = StringField("Nombre de la fuente", validators=[Length(max=80)])
    seisan = FileField(
        "Catálogo Seisan (select.out)",
        validators=[FileAllowed(["out", "txt", "dat"], "select.out")],
    )

    primary_source = RadioField(
        "Fuente local principal",
        choices=LOCALES,
        default=default_primary,
        validators=[DataRequired()],
    )
    submit = SubmitField("Validar y crear trabajo")

    def validate_period_end(self, field):  # noqa: N802 - API de WTForms
        if self.period_start.data and field.data and field.data < self.period_start.data:
            raise ValidationError("La fecha de término debe ser posterior a la de inicio.")

    def validate(self, extra_validators=None):  # noqa: N802 - API de WTForms
        valido = super().validate(extra_validators)

        seleccion = []
        if self.incluir_seiscomp.data:
            seleccion.append("seiscomp")
        if self.incluir_seisan.data:
            seleccion.append("seisan")

        if not seleccion:
            self.incluir_seiscomp.errors.append(
                "Seleccioná al menos una fuente local para comparar con eventquery."
            )
            valido = False

        if self.incluir_seiscomp.data and not (self.seiscomp.data and self.seiscomp.data.filename):
            self.seiscomp.errors.append("Subí la exportación de SeisComp o desmarcá la fuente.")
            valido = False

        if self.incluir_seisan.data and not (self.seisan.data and self.seisan.data.filename):
            self.seisan.errors.append("Subí select.out o desmarcá la fuente.")
            valido = False

        return valido


class SolicitudForm(FlaskForm):
    period_start = DateField("Desde", validators=[DataRequired()])
    period_end = DateField("Hasta", validators=[DataRequired()])
    server = StringField("Servidor SSH", validators=[DataRequired()], default=_ssh_host)
    remote_user = StringField("Usuario SSH", validators=[DataRequired()], default=_ssh_user)
    password = PasswordField("Contraseña SSH", validators=[DataRequired()])

    incluir_seisan = BooleanField("Incluir Seisan", default=True)
    incluir_seiscomp = BooleanField("Incluir SeisComp", default=False)
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
        choices=[("seiscomp", "SeisComp"), ("seisan", "Seisan")],
        default="seiscomp",
    )
    submit = SubmitField("Solicitar y descargar")

    def validate_period_end(self, field):  # noqa: N802 - API de WTForms
        if self.period_start.data and field.data and field.data < self.period_start.data:
            raise ValidationError("La fecha de término debe ser posterior a la de inicio.")

    def validate(self, extra_validators=None):  # noqa: N802 - API de WTForms
        valido = super().validate(extra_validators)
        if not self.incluir_seisan.data and not self.incluir_seiscomp.data:
            self.incluir_seisan.errors.append(
                "Seleccioná al menos una fuente local para descargar."
            )
            valido = False
        if self.incluir_seiscomp.data:
            from .services.seiscomp import configurada

            if self.radio_km.data is None:
                self.radio_km.errors.append("Indicá el radio de estaciones para SeisComp.")
                valido = False
            if not configurada():
                self.incluir_seiscomp.errors.append("SeisComp no está configurado (SEISCOMP_DB_*).")
                valido = False
        return valido


class ReintentarForm(FlaskForm):
    password = PasswordField("Contraseña SSH", validators=[DataRequired()])
    submit = SubmitField("Reintentar descarga")
