"""Comandos de línea de comandos de Flask."""

from __future__ import annotations

import os

import click
from flask import Flask
from flask.cli import with_appcontext

from .domain.catalogs.manifest import ManifestError
from .domain.catalogs.manifest import validar as validar_manifiesto
from .extensions import db
from .models import Job, User, UserRole
from .security import etiquetas_usuario, roles_de_usuario
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
    app.cli.add_command(set_analyst_code)
    app.cli.add_command(reset_password)
    app.cli.add_command(list_users)
    app.cli.add_command(delete_job)
    app.cli.add_command(reconcile_requests)
    app.cli.add_command(sources)


def _crear_admin() -> None:
    username = os.environ.get("ADMIN_USERNAME", "admin")
    password = os.environ.get("ADMIN_PASSWORD", "admin")
    existente = db.session.execute(
        db.select(User).filter_by(username=username)
    ).scalar_one_or_none()
    if existente is None:
        admin = User(username=username, role="admin", analyst_code="admin")
        admin.roles.append(UserRole(role="admin"))
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        click.echo(f"Usuario '{username}' creado.")
    else:
        click.echo(f"Usuario '{username}' ya existe.")


@click.group("sources")
def sources() -> None:
    """Validación y consulta del manifiesto de fuentes."""


@sources.command("validate")
@with_appcontext
def sources_validate() -> None:
    """Valida el manifiesto de fuentes antes de arrancar la app."""
    try:
        fuentes = validar_manifiesto()
    except ManifestError as exc:
        for error in exc.errores:
            click.echo(f"ERROR: {error}", err=True)
        raise click.ClickException("Manifiesto de fuentes inválido.") from exc
    click.echo(f"Manifiesto válido: {len(fuentes)} fuentes.")
    for fuente in fuentes:
        click.echo(f"  {fuente.id}\t{fuente.label}\t{fuente.role}")


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
    "roles",
    default="analista",
    show_default=True,
    help="Roles separados por coma.",
)
@click.option("--analyst-code", default="", help="Código corto de analista.")
@click.option("--analyst-aliases", default="", help="Alias separados por coma.")
@with_appcontext
def create_user(
    username: str,
    password: str,
    roles: str,
    analyst_code: str,
    analyst_aliases: str,
) -> None:
    """Crea un usuario nuevo."""
    try:
        user = crear_usuario(
            username,
            password,
            roles,
            analyst_code=analyst_code,
            analyst_aliases=analyst_aliases,
        )
    except UsuarioError as exc:
        raise click.ClickException(str(exc)) from exc
    registrar(
        "user.create",
        entity=user.username,
        meta={"roles": list(roles_de_usuario(user)), "origen": "cli"},
    )
    click.echo(
        f"Usuario '{user.username}' creado con roles "
        f"'{etiquetas_usuario(user)}'."
    )


@click.command("set-role")
@click.argument("username")
@click.argument("roles")
@with_appcontext
def set_role(username: str, roles: str) -> None:
    """Cambia los roles de un usuario (separados por coma)."""
    user = db.session.execute(
        db.select(User).filter_by(username=username)
    ).scalar_one_or_none()
    if user is None:
        raise click.ClickException(f"No existe el usuario '{username}'.")
    try:
        actualizar_usuario(user, roles, user.active)
    except UsuarioError as exc:
        raise click.ClickException(str(exc)) from exc
    registrar(
        "user.update",
        entity=user.username,
        meta={"roles": list(roles_de_usuario(user)), "origen": "cli"},
    )
    click.echo(
        f"Usuario '{user.username}' ahora tiene roles "
        f"'{etiquetas_usuario(user)}'."
    )


@click.command("set-analyst-code")
@click.argument("username")
@click.argument("analyst_code")
@click.option("--aliases", default="", help="Alias separados por coma.")
@with_appcontext
def set_analyst_code(username: str, analyst_code: str, aliases: str) -> None:
    """Asigna el código corto de analista a un usuario."""
    user = db.session.execute(
        db.select(User).filter_by(username=username)
    ).scalar_one_or_none()
    if user is None:
        raise click.ClickException(f"No existe el usuario '{username}'.")
    try:
        actualizar_usuario(
            user,
            list(roles_de_usuario(user)),
            user.active,
            analyst_code=analyst_code,
            analyst_aliases=aliases,
        )
    except UsuarioError as exc:
        raise click.ClickException(str(exc)) from exc
    registrar(
        "user.update",
        entity=user.username,
        meta={"codigo_analista": user.analyst_code, "origen": "cli"},
    )
    click.echo(
        f"Usuario '{user.username}' tiene código de analista "
        f"'{user.analyst_code}'."
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
            f"{etiquetas_usuario(user)}\t{estado}"
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


@click.command("reconcile-requests")
@with_appcontext
def reconcile_requests() -> None:
    """Marca como fallidas las solicitudes de descarga estancadas."""
    from .services.acquisition import reconciliar_solicitudes_estancadas

    total = reconciliar_solicitudes_estancadas()
    click.echo(f"Solicitudes estancadas marcadas como fallidas: {total}")
