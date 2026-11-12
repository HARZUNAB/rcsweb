"""Pruebas del estado y las advertencias de las fuentes de un trabajo."""

from __future__ import annotations

from pathlib import Path

from app.domain.catalogs import canonical
from app.extensions import db
from app.models import Job, JobSource, nuevo_uuid
from app.services import source_status
from app.services.pipeline import _avisar_fuentes_vacias


class _AdaptadorFalso:
    source_id = ""
    llamadas = 0
    resultado = {}

    def validar_periodo(self, job, rango=None):
        type(self).llamadas += 1
        return dict(type(self).resultado)


def _job(status="done") -> Job:
    job = Job(id=nuevo_uuid(), status=status)
    db.session.add(job)
    db.session.commit()
    return job


def _fuente(job: Job, message=None) -> JobSource:
    source = JobSource(
        job_id=job.id,
        kind="central",
        alias="Central",
        format="local_db",
        role="local_secundaria",
        status="ok",
        message=message,
    )
    db.session.add(source)
    db.session.commit()
    return source


def test_valida_fuente_directa_y_guarda_advertencia(app, monkeypatch):
    _AdaptadorFalso.llamadas = 0
    _AdaptadorFalso.resultado = {
        "ok": True,
        "errores": [],
        "advertencias": [
            "La base central no tiene eventos en el período seleccionado."
        ],
        "eventos": 0,
    }
    monkeypatch.setattr(
        source_status, "obtener_adaptador", lambda formato: _AdaptadorFalso()
    )
    job = _job()
    source = _fuente(job)

    assert source_status.validar_fuentes_directas(job) is True

    db.session.expire_all()
    source = db.session.get(JobSource, source.id)
    assert source.status == "ok"
    assert "no tiene eventos" in source.message
    assert _AdaptadorFalso.llamadas == 1


def test_marca_validada_sin_mensaje_y_no_repite(app, monkeypatch):
    _AdaptadorFalso.llamadas = 0
    _AdaptadorFalso.resultado = {
        "ok": True,
        "errores": [],
        "advertencias": [],
        "eventos": 3,
    }
    monkeypatch.setattr(
        source_status, "obtener_adaptador", lambda formato: _AdaptadorFalso()
    )
    job = _job()
    source = _fuente(job)

    assert source_status.validar_fuentes_directas(job) is True
    db.session.expire_all()
    source = db.session.get(JobSource, source.id)
    assert source.message == ""

    assert source_status.validar_fuentes_directas(job) is False
    assert _AdaptadorFalso.llamadas == 1


def test_avisa_fuente_vacia_al_terminar_pipeline(app, tmp_path):
    job = _job()
    source = _fuente(job, message=None)
    workspace = Path(tmp_path) / "ws"

    _avisar_fuentes_vacias(
        job,
        workspace,
        [("central", "local_db", "Central")],
    )

    db.session.expire_all()
    source = db.session.get(JobSource, source.id)
    assert "no devolvió eventos" in source.message


def test_no_sobrescribe_un_mensaje_especifico(app, tmp_path):
    job = _job()
    source = _fuente(
        job,
        message="La base central no tiene eventos en el período seleccionado.",
    )
    workspace = Path(tmp_path) / "ws"

    _avisar_fuentes_vacias(
        job,
        workspace,
        [("central", "local_db", "Central")],
    )

    db.session.expire_all()
    source = db.session.get(JobSource, source.id)
    assert "La base central" in source.message
    assert "no devolvió eventos" not in source.message


def test_no_avisa_si_la_fuente_tiene_eventos(app, tmp_path):
    job = _job()
    source = _fuente(job, message=None)
    workspace = Path(tmp_path) / "ws"
    canonical.escribir_registros(
        canonical.ruta_canonica(workspace, "central"),
        [{"event_id": "central:000000", "event_time": "2026-11-01 00:00:00"}],
    )

    _avisar_fuentes_vacias(
        job,
        workspace,
        [("central", "local_db", "Central")],
    )

    db.session.expire_all()
    source = db.session.get(JobSource, source.id)
    assert source.message is None
