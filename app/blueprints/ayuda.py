"""Página de ayuda y glosario de términos."""

from __future__ import annotations

from flask import Blueprint, render_template
from flask_login import login_required

from ..services import glossary

ayuda_bp = Blueprint("ayuda", __name__, url_prefix="/ayuda")


@ayuda_bp.get("")
@login_required
def index():
    return render_template("ayuda/index.html", grupos=glossary.grupos())
