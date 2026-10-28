"""Decoradores de autorización."""

from __future__ import annotations

from functools import wraps

from flask import abort
from flask_login import current_user, login_required


def admin_required(func):
    """Exige sesión iniciada y rol administrador."""

    @wraps(func)
    @login_required
    def envoltura(*args, **kwargs):
        if getattr(current_user, "role", None) != "admin":
            abort(403)
        return func(*args, **kwargs)

    return envoltura
