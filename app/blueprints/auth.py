"""Autenticación de usuarios."""

from __future__ import annotations

from urllib.parse import urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from ..extensions import db
from ..forms import LoginForm
from ..models import User

auth_bp = Blueprint("auth", __name__)


def _destino_seguro(valor: str | None) -> str | None:
    """Solo acepta rutas relativas del mismo sitio (evita open redirect)."""
    if not valor:
        return None
    partes = urlparse(valor)
    if partes.scheme or partes.netloc or not valor.startswith("/"):
        return None
    if valor.startswith("//"):
        return None
    return valor


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    form = LoginForm()
    if form.validate_on_submit():
        usuario = db.session.execute(
            db.select(User).filter_by(username=form.username.data.strip())
        ).scalar_one_or_none()

        if usuario and usuario.active and usuario.check_password(form.password.data):
            login_user(usuario, remember=form.remember.data)
            destino = _destino_seguro(request.args.get("next"))
            return redirect(destino or url_for("dashboard.index"))

        flash("Usuario o contraseña incorrectos.", "danger")

    return render_template("auth/login.html", form=form)


@auth_bp.post("/logout")
@login_required
def logout():
    logout_user()
    flash("Sesión cerrada.", "info")
    return redirect(url_for("auth.login"))
