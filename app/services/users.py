"""Alta y mantenimiento de usuarios desde la web y la CLI."""

from __future__ import annotations

import re

from sqlalchemy import func

from ..extensions import db
from ..models import User
from ..security import ROLES_VALIDOS
from .analysts import codigos_usuario, coincide, normalizar_nombre


class UsuarioError(ValueError):
    """Error de validación o de regla de negocio."""


def _validar(password: str) -> None:
    if len(password) < 8:
        raise UsuarioError("La contraseña debe tener al menos 8 caracteres.")


def _validar_codigo(
    usuario_id: int | None,
    analyst_code: str,
    analyst_aliases: str,
    role: str,
) -> None:
    codigo = (analyst_code or "").strip()
    alias = (analyst_aliases or "").strip()
    if role == "analista" and not codigo:
        raise UsuarioError(
            "El código de analista es obligatorio para el rol analista."
        )
    valores = [codigo] + re.split(r"[;,]", alias)
    codigos = []
    for valor in valores:
        normalizado = normalizar_nombre(valor)
        if normalizado and normalizado not in codigos:
            codigos.append(normalizado)
    if not codigos:
        return
    otros = db.session.execute(
        db.select(User).where(User.id != (usuario_id or -1))
    ).scalars()
    for otro in otros:
        for existente in codigos_usuario(otro):
            if any(coincide(nuevo, existente) for nuevo in codigos):
                raise UsuarioError(
                    f"El código o alias coincide con el usuario '{otro.username}'."
                )


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
    analyst_code: str = "",
    analyst_aliases: str = "",
) -> User:
    """Crea un usuario validando nombre, rol, contraseña y código."""
    nombre = (username or "").strip()
    if len(nombre) < 3:
        raise UsuarioError("El usuario debe tener al menos 3 caracteres.")
    if role not in ROLES_VALIDOS:
        raise UsuarioError(f"Rol desconocido: {role}.")
    _validar(password)
    _validar_codigo(None, analyst_code, analyst_aliases, role)
    existente = db.session.execute(
        db.select(User).filter_by(username=nombre)
    ).scalar_one_or_none()
    if existente is not None:
        raise UsuarioError(f"El usuario '{nombre}' ya existe.")

    usuario = User(
        username=nombre,
        role=role,
        active=active,
        analyst_code=(analyst_code or "").strip() or None,
        analyst_aliases=(analyst_aliases or "").strip() or None,
    )
    usuario.set_password(password)
    db.session.add(usuario)
    db.session.commit()
    return usuario


def actualizar_usuario(
    usuario: User,
    role: str,
    active: bool,
    analyst_code: str | None = None,
    analyst_aliases: str | None = None,
) -> User:
    """Cambia rol, estado y código sin dejar sin administradores activos."""
    if role not in ROLES_VALIDOS:
        raise UsuarioError(f"Rol desconocido: {role}.")
    codigo = usuario.analyst_code if analyst_code is None else analyst_code
    alias = (
        usuario.analyst_aliases
        if analyst_aliases is None
        else analyst_aliases
    )
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
    _validar_codigo(usuario.id, codigo or "", alias or "", role)
    usuario.role = role
    usuario.active = active
    usuario.analyst_code = (codigo or "").strip() or None
    usuario.analyst_aliases = (alias or "").strip() or None
    db.session.commit()
    return usuario


def reset_password(usuario: User, password: str) -> User:
    """Cambia la contraseña de un usuario (sin pedir la anterior)."""
    _validar(password)
    usuario.set_password(password)
    db.session.commit()
    return usuario
