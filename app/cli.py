"""Comandos de línea de comandos de Flask."""

from __future__ import annotations

import os

import click
from flask import Flask
from flask.cli import with_appcontext

from .extensions import db
from .models import Job, User
from .services.jobs import JobNoEliminable, eliminar_trabajo


def register_cli(app: Flask) -> None:
    app.cli.add_command(init_db)
    app.cli.add_command(seed_admin)
    app.cli.add_command(create_user)
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
@click.option("--role", default="analista", show_default=True)
@with_appcontext
def create_user(username: str, password: str, role: str) -> None:
    """Crea un usuario nuevo."""
    if db.session.execute(db.select(User).filter_by(username=username)).scalar_one_or_none():
        raise click.ClickException(f"El usuario '{username}' ya existe.")

    user = User(username=username, role=role)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    click.echo(f"Usuario '{username}' creado con rol '{role}'.")


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
