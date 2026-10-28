"""Fábrica de la aplicación Flask."""

from __future__ import annotations

from flask import Flask, render_template

from .config import Config
from .extensions import csrf, db, login_manager, migrate


def create_app(config_object: type | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_object or Config)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    # Importar los modelos antes de crear tablas (registra los mapeos).
    from . import models  # noqa: F401
    from .blueprints.auth import auth_bp
    from .blueprints.dashboard import dashboard_bp
    from .blueprints.health import health_bp
    from .blueprints.jobs import jobs_bp
    from .blueprints.results import results_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(jobs_bp)
    app.register_blueprint(results_bp)

    from .cli import register_cli

    register_cli(app)

    @app.errorhandler(404)
    def no_encontrado(error):  # pragma: no cover - plantilla simple
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def error_interno(error):  # pragma: no cover
        db.session.rollback()
        return render_template("errors/500.html"), 500

    @app.errorhandler(413)
    def archivo_demasiado_grande(error):
        return render_template("errors/413.html"), 413

    return app
