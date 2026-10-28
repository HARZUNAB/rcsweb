"""Registro de auditoría de acciones de usuario y del worker."""

from __future__ import annotations

from flask import has_request_context
from flask_login import current_user

from ..extensions import db
from ..models import AuditLog


def registrar(
    action: str,
    entity: str | None = None,
    meta: dict | None = None,
    user_id: int | None = None,
) -> None:
    """Agrega una entrada de auditoría sin romper la operación principal."""
    try:
        if user_id is None and has_request_context():
            if current_user and current_user.is_authenticated:
                user_id = current_user.id
        db.session.add(
            AuditLog(
                user_id=user_id,
                action=action,
                entity=entity,
                meta=meta or {},
            )
        )
        db.session.commit()
    except Exception:  # noqa: BLE001 - la auditoría no debe tumbar la acción
        db.session.rollback()
