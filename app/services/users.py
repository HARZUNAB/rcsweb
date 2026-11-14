"""Alta y mantenimiento de usuarios desde la web y la CLI."""

from __future__ import annotations

import re

from sqlalchemy import func

from ..extensions import db
from ..models import User, UserRole
from ..security import ROLES_VALIDOS, roles_de_usuario
from .analysts import codigos_usuario, coincide, normalizar_nombre


class UsuarioError(ValueError):
    """Error de validación o de regla de negocio."""


def _validar(password: str) -> None:
    if len(password) < 8:
        raise UsuarioError("La contraseña debe tener al menos 8 caracteres.")


def _normalizar_roles(roles) -> tuple[str, ...]:
    """Acepta un rol, una lista o una cadena separada por coma."""
    if isinstance(roles, str):
        valores = re.split(r"[,;]", roles)
    else:
        valores = list(roles or ())
    limpios = {str(valor).strip() for valor in valores if str(valor).strip()}
    if not limpios:
        raise UsuarioError("Seleccione al menos un rol.")
    desconocidos = sorted(limpios - set(ROLES_VALIDOS))
    if desconocidos:
        raise UsuarioError(f"Rol desconocido: {desconocidos[0]}.")
    orden = {rol: posicion for posicion, rol in enumerate(ROLES_VALIDOS)}
    return tuple(sorted(limpios, key=lambda rol: orden[rol]))


def _validar_codigo(
    usuario_id: int | None,
    analyst_code: str,
    analyst_aliases: str,
    roles: tuple[str, ...],
) -> None:
    codigo = (analyst_code or "").strip()
    alias = (analyst_aliases or "").strip()
    if "analista" in roles and not codigo:
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
    consulta = (
        db.select(func.count(User.id))
        .select_from(User)
        .where(
            User.active.is_(True),
            db.or_(
                User.role == "admin",
                User.roles.any(UserRole.role == "admin"),
            ),
        )
    )
    if exclude_id is not None:
        consulta = consulta.where(User.id != exclude_id)
    return db.session.execute(consulta).scalar_one()


def _aplicar_roles(usuario: User, roles: tuple[str, ...]) -> None:
    usuario.roles.clear()
    usuario.roles.extend(UserRole(role=rol) for rol in roles)
    usuario.role = roles[0]


def crear_usuario(
    username: str,
    password: str,
    roles,
    active: bool = True,
    analyst_code: str = "",
    analyst_aliases: str = "",
) -> User:
    """Crea un usuario validando nombre, roles, contraseña y código."""
    nombre = (username or "").strip()
    if len(nombre) < 3:
        raise UsuarioError("El usuario debe tener al menos 3 caracteres.")
    roles_norm = _normalizar_roles(roles)
    _validar(password)
    _validar_codigo(None, analyst_code, analyst_aliases, roles_norm)
    existente = db.session.execute(
        db.select(User).filter_by(username=nombre)
    ).scalar_one_or_none()
    if existente is not None:
        raise UsuarioError(f"El usuario '{nombre}' ya existe.")

    usuario = User(
        username=nombre,
        role=roles_norm[0],
        active=active,
        analyst_code=(analyst_code or "").strip() or None,
        analyst_aliases=(analyst_aliases or "").strip() or None,
    )
    _aplicar_roles(usuario, roles_norm)
    usuario.set_password(password)
    db.session.add(usuario)
    db.session.commit()
    return usuario


def actualizar_usuario(
    usuario: User,
    roles,
    active: bool,
    analyst_code: str | None = None,
    analyst_aliases: str | None = None,
) -> User:
    """Cambia roles, estado y código sin dejar sin administradores activos."""
    roles_norm = _normalizar_roles(roles)
    codigo = usuario.analyst_code if analyst_code is None else analyst_code
    alias = (
        usuario.analyst_aliases
        if analyst_aliases is None
        else analyst_aliases
    )
    roles_previos = set(roles_de_usuario(usuario))
    era_admin_activo = "admin" in roles_previos and usuario.active
    sera_admin_activo = "admin" in roles_norm and active
    if (
        era_admin_activo
        and not sera_admin_activo
        and _admin_activo_count(exclude_id=usuario.id) == 0
    ):
        raise UsuarioError(
            "Debe quedar al menos un administrador activo."
        )
    _validar_codigo(usuario.id, codigo or "", alias or "", roles_norm)
    _aplicar_roles(usuario, roles_norm)
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
