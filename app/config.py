"""Configuración de la aplicación.

Todo se toma de variables de entorno para que el mismo código funcione en
desarrollo (Docker Compose) y en despliegue. Los valores por defecto están
pensados para el compose de desarrollo.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy.pool import StaticPool

BASE_DIR = Path(__file__).resolve().parent.parent


def _bool(nombre: str, defecto: bool = False) -> bool:
    return os.environ.get(nombre, str(int(defecto))).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


class Config:
    # Flask
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-cambiar")
    APP_VERSION = os.environ.get("APP_VERSION", "0.4.1")
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_UPLOAD_MB", "200")) * 1024 * 1024

    # Base de datos propia (lectura/escritura)
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "postgresql+psycopg://rcs:rcs@db:5432/rcs"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # Sesiones
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)
    WTF_CSRF_TIME_LIMIT = None

    # Rutas de trabajo
    WORKSPACE_ROOT = Path(os.environ.get("WORKSPACE_ROOT", BASE_DIR / "workspace"))
    RCS_CORE_PATH = Path(os.environ.get("RCS_CORE_PATH", "/opt/rcs-core"))
    DATOS_PATH = Path(os.environ.get("DATOS_PATH", "/data"))

    # Celery
    CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0")
    CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/1")


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_ENGINE_OPTIONS = {
        "poolclass": StaticPool,
        "connect_args": {"check_same_thread": False},
    }
    WTF_CSRF_ENABLED = False
    SERVER_NAME = "localhost"
