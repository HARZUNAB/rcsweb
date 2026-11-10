"""Pruebas del adaptador de la base central."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.domain.catalogs.adapters.central import (
    Adaptador,
    _estado_texto,
    _periodo,
    limpiar_cache_disponibilidad,
)
from app.extensions import db
from app.models import Job, User, nuevo_uuid


@pytest.fixture(autouse=True)
def _cache_limpia():
    limpiar_cache_disponibilidad()
    yield
    limpiar_cache_disponibilidad()


def _job(usuario_id: int) -> Job:
    job = Job(
        id=nuevo_uuid(),
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 31, 23, 59, 59, tzinfo=UTC),
        status="queued",
        created_by_id=usuario_id,
    )
    db.session.add(job)
    db.session.commit()
    return job


def _usuario(nombre: str, rol: str, codigo: str = "") -> User:
    usuario = User(username=nombre, role=rol, analyst_code=codigo)
    usuario.set_password("secret")
    db.session.add(usuario)
    db.session.commit()
    return usuario


def _eventos():
    return [
        {
            "event_id": "e-1",
            "published": False,
            "origin_id": "o-1",
            "author": "eatl",
            "status": "REVIEWED",
            "origin_time": datetime(2026, 10, 1, 0, 0, tzinfo=UTC),
            "latitude": -30.0,
            "longitude": -71.0,
            "depth": 10.0,
            "magnitude_value": 2.5,
            "magnitude_type": "ML",
        },
        {
            "event_id": "e-2",
            "published": True,
            "origin_id": "o-2",
            "author": "otro",
            "status": "final",
            "origin_time": datetime(2026, 10, 2, 0, 0, tzinfo=UTC),
            "latitude": -31.0,
            "longitude": -72.0,
            "depth": 20.0,
            "magnitude_value": 3.0,
            "magnitude_type": "ML",
        },
    ]


def _tensores():
    return [
        {"event_id": "e-1", "origin_id": "o-1", "tensor_id": "t-1",
         "method": "SCMT", "mechanism": "DC", "strike1": 10.0,
         "dip1": 20.0, "rake1": 30.0, "strike2": 40.0, "dip2": 50.0,
         "rake2": 60.0, "m_rr": 1e18, "m_tt": -1e18, "m_pp": 0.0,
         "m_rt": 0.0, "m_rp": 0.0, "m_tp": 0.0,
         "scalar_moment": 1e18},
        {"event_id": "e-2", "origin_id": "o-2", "tensor_id": "t-2",
         "method": "SCMT", "mechanism": "DC", "strike1": 0.0,
         "dip1": 0.0, "rake1": 0.0, "strike2": 0.0, "dip2": 0.0,
         "rake2": 0.0, "m_rr": 0.0, "m_tt": 0.0, "m_pp": 0.0,
         "m_rt": 0.0, "m_rp": 0.0, "m_tp": 0.0,
         "scalar_moment": 0.0},
    ]


def test_estado_normalizado():
    assert _estado_texto("REVIEWED") == "Revisado"
    assert _estado_texto("final") == "Final"
    assert _estado_texto("confirmed") == "Confirmado"
    assert _estado_texto("automatic") == "Automático"
    assert _estado_texto("manual") == "Manual"
    assert _estado_texto("desconocido") == "desconocido"


def test_periodo_desde_el_job(app):
    with app.app_context():
        usuario = _usuario("ana", "analista", "eatl")
        job = _job(usuario.id)
        inicio, fin = _periodo(job)
        assert inicio == datetime(2026, 10, 1, tzinfo=UTC)
        assert fin == datetime(2026, 10, 31, 23, 59, 59, tzinfo=UTC)


def test_exportar_filtra_por_analista(app, tmp_path, monkeypatch):
    with app.app_context():
        usuario = _usuario("ana", "analista", "eatl")
        job = _job(usuario.id)
        adaptador = Adaptador()
        adaptador.source_id = "central"
        monkeypatch.setattr(
            adaptador, "_consultar", lambda _inicio, _fin: (_eventos(), _tensores())
        )

        adaptador.exportar(tmp_path, job)

        eventos = (tmp_path / "datos/central_parametros.csv").read_text(
            encoding="utf-8"
        )
        assert "eatl" in eventos
        assert "otro" not in eventos
        assert "Sí" not in eventos
        assert "Revisado" in eventos

        tensores = (tmp_path / "datos/central_tensores.csv").read_text(
            encoding="utf-8"
        )
        assert "e-1" in tensores
        assert "e-2" not in tensores


def test_exportar_admin_ve_todo(app, tmp_path, monkeypatch):
    with app.app_context():
        usuario = _usuario("admin2", "admin", "")
        job = _job(usuario.id)
        adaptador = Adaptador()
        adaptador.source_id = "central"
        monkeypatch.setattr(
            adaptador, "_consultar", lambda _inicio, _fin: (_eventos(), _tensores())
        )

        adaptador.exportar(tmp_path, job)

        eventos = (tmp_path / "datos/central_parametros.csv").read_text(
            encoding="utf-8"
        )
        assert "eatl" in eventos
        assert "otro" in eventos
        assert "Sí" in eventos


def test_extension_de_tensores_solo_si_hay_filas(app):
    with app.app_context():
        adaptador = Adaptador()
        adaptador.source_id = "central"
        trabajo = app.config["WORKSPACE_ROOT"] / "sin_tensores"
        (trabajo / "datos").mkdir(parents=True, exist_ok=True)
        (trabajo / "datos/central_tensores.csv").write_text(
            "id_evento,id_origen,tensor_id\n", encoding="utf-8"
        )

        assert adaptador.extensiones(None, "", trabajo) == {}

        (trabajo / "datos/central_tensores.csv").write_text(
            "id_evento,id_origen,tensor_id\ne-1,o-1,t-1\n", encoding="utf-8"
        )
        assert adaptador.extensiones(None, "", trabajo) == {
            "tensores": "datos/central_tensores.csv"
        }


class _CursorFalso:
    def __init__(self, filas):
        self.filas = filas

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def execute(self, *_args, **_kwargs):
        return None

    def fetchall(self):
        return self.filas


class _ConexionFalsa:
    def __init__(self, filas):
        self.filas = filas

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def cursor(self):
        return _CursorFalso(self.filas)


class _CursorRango:
    def __init__(self, rango):
        self.rango = rango

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def execute(self, *_args, **_kwargs):
        return None

    def fetchone(self):
        return self.rango


class _ConexionRango:
    def __init__(self, rango):
        self.rango = rango

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def cursor(self):
        return _CursorRango(self.rango)


def test_disponibilidad_global_y_cache(app, monkeypatch):
    with app.app_context():
        app.config["RCS_CENTRAL_DSN"] = "postgresql://fake"
        adaptador = Adaptador()
        adaptador.source_id = "central"
        rango = (
            datetime(1982, 9, 18, tzinfo=UTC),
            datetime(2025, 3, 31, tzinfo=UTC),
        )
        llamados = []

        def _conectar():
            llamados.append(1)
            return _ConexionRango(rango)

        monkeypatch.setattr(adaptador, "_conectar", _conectar)

        primero = adaptador.disponibilidad()
        segundo = adaptador.disponibilidad()

        assert primero == {"desde": rango[0], "hasta": rango[1]}
        assert segundo == primero
        assert len(llamados) == 1


def test_validar_periodo_filtra_por_analista(app, monkeypatch):
    with app.app_context():
        usuario = _usuario("ana2", "analista", "eatl")
        job = _job(usuario.id)
        adaptador = Adaptador()
        adaptador.source_id = "central"
        filas = [
            ("eatl", datetime(2026, 10, 1, tzinfo=UTC)),
            ("otro", datetime(2026, 10, 2, tzinfo=UTC)),
        ]
        monkeypatch.setattr(
            adaptador, "_conectar", lambda: _ConexionFalsa(filas)
        )

        resultado = adaptador.validar_periodo(job)

        assert resultado["ok"] is True
        assert resultado["eventos"] == 1


def test_validar_periodo_sin_eventos_es_advertencia(app, monkeypatch):
    with app.app_context():
        usuario = _usuario("ana3", "analista", "eatl")
        job = _job(usuario.id)
        adaptador = Adaptador()
        adaptador.source_id = "central"
        monkeypatch.setattr(adaptador, "_conectar", lambda: _ConexionFalsa([]))
        rango = {
            "desde": datetime(1982, 9, 18, tzinfo=UTC),
            "hasta": datetime(2025, 3, 31, tzinfo=UTC),
        }

        resultado = adaptador.validar_periodo(job, rango)

        assert resultado["ok"] is True
        assert resultado["eventos"] == 0
        assert resultado["errores"] == []
        assert "Rango disponible" in " ".join(resultado["advertencias"])


def test_validar_periodo_sin_codigo_es_advertencia(app, monkeypatch):
    with app.app_context():
        usuario = _usuario("consulta", "consulta", "")
        job = _job(usuario.id)
        adaptador = Adaptador()
        adaptador.source_id = "central"
        monkeypatch.setattr(adaptador, "_conectar", lambda: _ConexionFalsa([]))

        resultado = adaptador.validar_periodo(job)

        assert resultado["ok"] is True
        assert resultado["eventos"] == 0
        assert "código de analista" in " ".join(resultado["advertencias"])


def test_validar_periodo_error_de_conexion(app, monkeypatch):
    with app.app_context():
        usuario = _usuario("ana4", "analista", "eatl")
        job = _job(usuario.id)
        adaptador = Adaptador()
        adaptador.source_id = "central"

        def _falla():
            raise RuntimeError("sin conexión")

        monkeypatch.setattr(adaptador, "_conectar", _falla)

        resultado = adaptador.validar_periodo(job)

        assert resultado["ok"] is False
        assert "sin conexión" in " ".join(resultado["errores"])
