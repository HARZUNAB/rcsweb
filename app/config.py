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
    APP_VERSION = os.environ.get("APP_VERSION", "0.8.0")
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
    RCS_CORE_PATH = Path(
        os.environ.get("RCS_CORE_PATH", BASE_DIR / "core")
    ).resolve()
    RCS_CORE_DATA = Path(
        os.environ.get("RCS_CORE_DATA", BASE_DIR / "core_data")
    ).resolve()
    RCS_CATALOGO_SISMICIDAD = os.environ.get(
        "RCS_CATALOGO_SISMICIDAD", "base_2018_2026.dat"
    )
    DATOS_PATH = Path(os.environ.get("DATOS_PATH", "/data"))

    # Listas de estaciones de Seisan. El manifiesto declara el nombre de la
    # variable; la ruta real vive en el entorno.
    RCS_SEISAN_STATIONS_DIR = os.environ.get(
        "RCS_SEISAN_STATIONS_DIR",
        str(DATOS_PATH / "csn" / "datseisan"),
    )

    # Enriquecimiento temporal de residuales desde fuentes locales.
    RCS_ENRIQUECER_RESIDUALES = _bool("RCS_ENRIQUECER_RESIDUALES", True)

    # Fuente Central: base CSN de solo lectura. El manifiesto declara el nombre
    # de la variable para no fijar la conexión en el código.
    RCS_CENTRAL_DSN = os.environ.get("RCS_CENTRAL_DSN", "").strip()

    # Informes de revisión
    RCS_INFORME_MAX_EVENTOS = int(
        os.environ.get("RCS_INFORME_MAX_EVENTOS") or 50
    )
    RCS_EVIDENCIA_MAX_MB = int(
        os.environ.get("RCS_EVIDENCIA_MAX_MB") or 20
    )
    # Exportación temporal del catálogo completo de una fuente local.
    RCS_CATALOGO_COMPLETO_ACTIVO = _bool(
        "RCS_CATALOGO_COMPLETO_ACTIVO", True
    )
    # Durante desarrollo la notificación por correo parte desmarcada.
    # Cambie a 1 para preseleccionar el envío cuando se solicite una revisión.
    RCS_NOTIFICAR_REVISION_DEFAULT = _bool(
        "RCS_NOTIFICAR_REVISION_DEFAULT", False
    )
    # correo: aviso autónomo con el detalle en el informe adjunto.
    # plataforma: formato anterior con enlace a la solicitud.
    RCS_NOTIFICACION_MODO = (
        os.environ.get("RCS_NOTIFICACION_MODO", "correo").strip().lower()
        or "correo"
    )
    RCS_NOTIFICACION_COPIAS_OBLIGATORIAS = _bool(
        "RCS_NOTIFICACION_COPIAS_OBLIGATORIAS", False
    )
    RCS_PUBLIC_URL = os.environ.get("RCS_PUBLIC_URL", "").strip()

    # Correo saliente para notificar solicitudes de revisión
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "").strip()
    MAIL_PORT = int(os.environ.get("MAIL_PORT") or 25)
    MAIL_USE_SSL = _bool("MAIL_USE_SSL", False)
    MAIL_USE_TLS = _bool("MAIL_USE_TLS", False)
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "").strip()
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "")
    MAIL_DEFAULT_SENDER = os.environ.get(
        "MAIL_DEFAULT_SENDER", "rcsweb@localhost"
    ).strip()
    MAIL_FROM_NAME = os.environ.get("MAIL_FROM_NAME", "RCS Web").strip()
    MAIL_SIGNATURE = os.environ.get(
        "MAIL_SIGNATURE",
        "RCS Web|Centro Sismológico Nacional|Universidad de Chile",
    )
    MAIL_TIMEOUT = int(os.environ.get("MAIL_TIMEOUT") or 10)
    MAIL_SUPPRESS_SEND = _bool("MAIL_SUPPRESS_SEND", False)

    # Celery
    CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0")
    CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/1")

    # Servicio auxiliar de disponibilidad de formas de onda
    RCS_DISPONIBILIDAD_URL = os.environ.get(
        "RCS_DISPONIBILIDAD_URL", ""
    ).strip()
    RCS_DISPONIBILIDAD_TOKEN = os.environ.get(
        "RCS_DISPONIBILIDAD_TOKEN", ""
    ).strip()
    RCS_DISPONIBILIDAD_TIMEOUT = int(
        os.environ.get("RCS_DISPONIBILIDAD_TIMEOUT") or 240
    )
    RCS_DISPONIBILIDAD_MAX_ESTACIONES = int(
        os.environ.get("RCS_DISPONIBILIDAD_MAX_ESTACIONES") or 150
    )
    RCS_DISPONIBILIDAD_MAX_STREAMS = int(
        os.environ.get("RCS_DISPONIBILIDAD_MAX_STREAMS") or 5000
    )

    # Cobertura de picks cercanos
    RCS_PICKS_RADIO_KM = float(
        os.environ.get("RCS_PICKS_RADIO_KM") or 250
    )
    RCS_PICKS_CERCA_KM = float(
        os.environ.get("RCS_PICKS_CERCA_KM") or 100
    )
    RCS_PICKS_MAX_CANDIDATAS = int(
        os.environ.get("RCS_PICKS_MAX_CANDIDATAS") or 60
    )


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
    MAIL_SUPPRESS_SEND = True
    MAIL_SERVER = ""
    RCS_PUBLIC_URL = "http://localhost"
