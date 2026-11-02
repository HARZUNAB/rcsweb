"""Comandos de línea de comandos de Flask."""

from __future__ import annotations

import os

import click
from flask import Flask
from flask.cli import with_appcontext

from .extensions import db
from .models import Job, User
from .security import ETIQUETAS_ROL, ROLES_VALIDOS
from .services.audit import registrar
from .services.jobs import JobNoEliminable, eliminar_trabajo
from .services.users import (
    UsuarioError,
    actualizar_usuario,
    crear_usuario,
)
from .services.users import (
    reset_password as cambiar_password,
)


def register_cli(app: Flask) -> None:
    app.cli.add_command(init_db)
    app.cli.add_command(seed_admin)
    app.cli.add_command(create_user)
    app.cli.add_command(set_role)
    app.cli.add_command(reset_password)
    app.cli.add_command(list_users)
    app.cli.add_command(delete_job)


def _crear_admin() -> None:
    username = os.environ.get("ADMIN_USERNAME", "admin")
    password = os.environ.get("ADMIN_PASSWORD", "admin")
    existente = db.session.execute(
        db.select(User).filter_by(username=username)
    ).scalar_one_or_none()
    if existente is None:
        admin = User(username=username, role="admin")
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        click.echo(f"Usuario '{username}' creado.")
    else:
        click.echo(f"Usuario '{username}' ya existe.")


@click.command("init-db")
@with_appcontext
def init_db() -> None:
    """Crea las tablas y el usuario administrador inicial (desarrollo)."""
    db.create_all()
    _crear_admin()
    click.echo("Base de datos inicializada.")


@click.command("seed-admin")
@with_appcontext
def seed_admin() -> None:
    """Crea el administrador inicial si no existe."""
    _crear_admin()


@click.command("create-user")
@click.argument("username")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
@click.option(
    "--role",
    type=click.Choice(ROLES_VALIDOS),
    default="analista",
    show_default=True,
)
@with_appcontext
def create_user(username: str, password: str, role: str) -> None:
    """Crea un usuario nuevo."""
    try:
        user = crear_usuario(username, password, role)
    except UsuarioError as exc:
        raise click.ClickException(str(exc)) from exc
    registrar(
        "user.create",
        entity=user.username,
        meta={"rol": user.role, "origen": "cli"},
    )
    click.echo(
        f"Usuario '{user.username}' creado con rol "
        f"'{ETIQUETAS_ROL.get(user.role, user.role)}'."
    )


@click.command("set-role")
@click.argument("username")
@click.argument("role", type=click.Choice(ROLES_VALIDOS))
@with_appcontext
def set_role(username: str, role: str) -> None:
    """Cambia el rol de un usuario."""
    user = db.session.execute(
        db.select(User).filter_by(username=username)
    ).scalar_one_or_none()
    if user is None:
        raise click.ClickException(f"No existe el usuario '{username}'.")
    try:
        actualizar_usuario(user, role, user.active)
    except UsuarioError as exc:
        raise click.ClickException(str(exc)) from exc
    registrar(
        "user.update",
        entity=user.username,
        meta={"rol": user.role, "origen": "cli"},
    )
    click.echo(
        f"Usuario '{user.username}' ahora tiene rol "
        f"'{ETIQUETAS_ROL.get(user.role, user.role)}'."
    )


@click.command("reset-password")
@click.argument("username")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
@click.option("--activar/--no-activar", default=True)
@with_appcontext
def reset_password(username: str, password: str, activar: bool) -> None:
    """Restablece la contraseña de un usuario."""
    user = db.session.execute(
        db.select(User).filter_by(username=username)
    ).scalar_one_or_none()
    if user is None:
        raise click.ClickException(f"No existe el usuario '{username}'.")
    try:
        cambiar_password(user, password)
    except UsuarioError as exc:
        raise click.ClickException(str(exc)) from exc
    if activar and not user.active:
        user.active = True
        db.session.commit()
    registrar(
        "user.password_reset",
        entity=user.username,
        meta={"origen": "cli", "activo": user.active},
    )
    click.echo(f"Contraseña de '{user.username}' restablecida.")


@click.command("list-users")
@with_appcontext
def list_users() -> None:
    """Lista los usuarios, su rol y estado."""
    usuarios = (
        db.session.execute(db.select(User).order_by(User.username))
        .scalars()
        .all()
    )
    if not usuarios:
        click.echo("No hay usuarios.")
        return
    for user in usuarios:
        estado = "activo" if user.active else "inactivo"
        click.echo(
            f"{user.username}\t"
            f"{ETIQUETAS_ROL.get(user.role, user.role)}\t{estado}"
        )


@click.command("delete-job")
@click.argument("job_id")
@with_appcontext
def delete_job(job_id: str) -> None:
    """Elimina un trabajo terminado y su workspace."""
    job = db.session.get(Job, job_id)
    if job is None:
        raise click.ClickException(f"No existe el trabajo '{job_id}'.")
    try:
        eliminar_trabajo(job, origen="cli")
    except JobNoEliminable as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Trabajo '{job_id}' eliminado.")
