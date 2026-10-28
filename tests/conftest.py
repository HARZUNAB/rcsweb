"""Fixtures comunes de la suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.models import User

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.fixture()
def app(tmp_path):
    aplicacion = create_app(TestConfig)
    aplicacion.config["WORKSPACE_ROOT"] = tmp_path / "workspace"
    aplicacion.config["RCS_CORE_PATH"] = tmp_path / "core"

    contexto = aplicacion.app_context()
    contexto.push()
    db.create_all()
    usuario = User(username="tester", role="admin")
    usuario.set_password("secret")
    db.session.add(usuario)
    db.session.commit()

    yield aplicacion

    db.session.remove()
    db.drop_all()
    contexto.pop()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def login(client):
    def _login():
        return client.post("/login", data={"username": "tester", "password": "secret"})

    return _login


@pytest.fixture()
def samples():
    return SAMPLES


@pytest.fixture()
def sin_celery(monkeypatch):
    llamados = []

    def _encolar(job_id):
        llamados.append(job_id)

    monkeypatch.setattr("app.blueprints.jobs.encolar_trabajo", _encolar)
    return llamados
