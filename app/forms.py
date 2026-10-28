"""Formularios WTForms."""

from __future__ import annotations

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import BooleanField, DateField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Length, ValidationError


class LoginForm(FlaskForm):
    username = StringField("Usuario", validators=[DataRequired(), Length(min=3, max=80)])
    password = PasswordField("Contraseña", validators=[DataRequired()])
    remember = BooleanField("Recordarme")
    submit = SubmitField("Entrar")


class JobForm(FlaskForm):
    period_start = DateField("Desde", validators=[DataRequired()])
    period_end = DateField("Hasta", validators=[DataRequired()])

    seisan = FileField(
        "Catálogo Seisan (select.out)",
        validators=[FileRequired(), FileAllowed(["out", "txt", "dat"], "select.out")],
    )
    eventquery = FileField(
        "Catálogo eventquery (CSV)",
        validators=[FileRequired(), FileAllowed(["csv"], "un CSV de eventquery")],
    )
    seiscomp = FileField(
        "Exportación de SeisComp (opcional)",
        validators=[FileAllowed(["csv"], "un CSV de SeisComp")],
    )
    submit = SubmitField("Crear y procesar")

    def validate_period_end(self, field):  # noqa: N802 - API de WTForms
        if self.period_start.data and field.data and field.data < self.period_start.data:
            raise ValidationError("La fecha de término debe ser posterior a la de inicio.")
