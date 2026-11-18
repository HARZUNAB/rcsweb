"""Página de ayuda y glosario de términos."""

from __future__ import annotations

from urllib.parse import urlparse

from flask import Blueprint, render_template, request
from flask_login import login_required

from ..services import glossary

ayuda_bp = Blueprint("ayuda", __name__, url_prefix="/ayuda")


def _volver_seguro(valor: str | None) -> str | None:
    """Acepta solo una ruta interna segura para volver desde el glosario."""
    if not valor:
        return None
    ruta = valor.strip()
    if not ruta or len(ruta) > 2000:
        return None
    if any(caracter in ruta for caracter in "\r\n\t\\"):
        return None
    partes = urlparse(ruta)
    if partes.scheme or partes.netloc:
        return None
    if not ruta.startswith("/") or ruta.startswith("//"):
        return None
    if partes.path == "/ayuda" or partes.path.startswith("/ayuda/"):
        return None
    return ruta


@ayuda_bp.get("")
@login_required
def index():
    volver = _volver_seguro(request.args.get("volver"))
    return render_template(
        "ayuda/index.html",
        grupos=glossary.grupos(),
        volver=volver,
    )
