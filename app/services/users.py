"""Alta y mantenimiento de usuarios desde la web y la CLI."""

from __future__ import annotations

from sqlalchemy import func

from ..extensions import db
from ..models import User
from ..security import ROLES_VALIDOS


class UsuarioError(ValueError):
    """Error de validación o de regla de negocio."""


def _validar(password: str) -> None:
    if len(password) < 8:
        raise UsuarioError("La contraseña debe tener al menos 8 caracteres.")


def _admin_activo_count(exclude_id: int | None = None) -> int:
    consulta = db.select(func.count()).select_from(User).where(
        User.role == "admin", User.active.is_(True)
    )
    if exclude_id is not None:
        consulta = consulta.where(User.id != exclude_id)
    return db.session.execute(consulta).scalar_one()


def crear_usuario(
    username: str,
    password: str,
    role: str,
    active: bool = True,
) -> User:
    """Crea un usuario validando nombre, rol y contraseña."""
    nombre = (username or "").strip()
    if len(nombre) < 3:
        raise UsuarioError("El usuario debe tener al menos 3 caracteres.")
    if role not in ROLES_VALIDOS:
        raise UsuarioError(f"Rol desconocido: {role}.")
    _validar(password)
    existente = db.session.execute(
        db.select(User).filter_by(username=nombre)
    ).scalar_one_or_none()
    if existente is not None:
        raise UsuarioError(f"El usuario '{nombre}' ya existe.")

    usuario = User(username=nombre, role=role, active=active)
    usuario.set_password(password)
    db.session.add(usuario)
    db.session.commit()
    return usuario


def actualizar_usuario(usuario: User, role: str, active: bool) -> User:
    """Cambia rol y estado sin dejar el sistema sin administradores activos."""
    if role not in ROLES_VALIDOS:
        raise UsuarioError(f"Rol desconocido: {role}.")
    era_admin_activo = usuario.role == "admin" and usuario.active
    sera_admin_activo = role == "admin" and active
    if (
        era_admin_activo
        and not sera_admin_activo
        and _admin_activo_count(exclude_id=usuario.id) == 0
    ):
        raise UsuarioError(
            "Debe quedar al menos un administrador activo."
        )
    usuario.role = role
    usuario.active = active
    db.session.commit()
    return usuario


def reset_password(usuario: User, password: str) -> User:
    """Cambia la contraseña de un usuario (sin pedir la anterior)."""
    _validar(password)
    usuario.set_password(password)
    db.session.commit()
    return usuario
