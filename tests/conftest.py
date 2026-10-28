"""Fixtures comunes de la suite."""

from __future__ import annotations

import pytest

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.models import User


@pytest.fixture()
def app():
    aplicacion = create_app(TestConfig)

    with aplicacion.app_context():
        db.create_all()
        usuario = User(username="tester", role="admin")
        usuario.set_password("secret")
        db.session.add(usuario)
        db.session.commit()

    yield aplicacion

    with aplicacion.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()
