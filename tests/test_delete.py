"""Pruebas de eliminación de trabajos y limpieza administrativa."""

from __future__ import annotations

from datetime import UTC, datetime

from app.extensions import db
from app.models import AuditLog, Job, JobFile, User, nuevo_uuid
from app.services.jobs import JobNoEliminable, eliminar_trabajo
from app.services.workspace import crear_workspace


def _usuario(nombre="tester"):
    return db.session.execute(db.select(User).filter_by(username=nombre)).scalar_one()


def _job(status="done", creador=None, con_archivo=True):
    job = Job(
        id=nuevo_uuid(),
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 31, tzinfo=UTC),
        status=status,
        created_by_id=(creador or _usuario()).id,
    )
    db.session.add(job)
    db.session.commit()
    workspace = crear_workspace(job.id)
    if con_archivo:
        (workspace / "resultados").mkdir(parents=True, exist_ok=True)
        (workspace / "resultados" / "demo.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        db.session.add(
            JobFile(
                job_id=job.id,
                kind="seisan",
                original_name="select.out",
                stored_name="inputs/select.out",
                size=8,
            )
        )
        db.session.commit()
    return job, workspace


def test_eliminar_trabajo_borra_db_archivos_y_audita(client, login):
    login()
    job, workspace = _job()

    respuesta = client.post(f"/jobs/{job.id}/eliminar")

    assert respuesta.status_code == 302
    assert db.session.get(Job, job.id) is None
    assert not workspace.exists()
    assert (
        db.session.execute(db.select(JobFile).filter_by(job_id=job.id)).scalar_one_or_none() is None
    )
    auditoria = db.session.execute(
        db.select(AuditLog).filter_by(action="job.delete", entity=job.id)
    ).scalar_one()
    assert auditoria.meta["origen"] == "web"
    assert auditoria.meta["estado"] == "done"


def test_no_elimina_trabajo_activo(client, login):
    login()
    job, workspace = _job(status="running")

    respuesta = client.post(f"/jobs/{job.id}/eliminar")

    assert respuesta.status_code == 302
    assert db.session.get(Job, job.id) is not None
    assert workspace.exists()
    assert (
        db.session.execute(
            db.select(AuditLog).filter_by(action="job.delete", entity=job.id)
        ).scalar_one_or_none()
        is None
    )


def test_creador_no_admin_no_puede_eliminar_trabajo_ajeno(client):
    normal = User(username="normal", role="analista")
    normal.set_password("clave")
    db.session.add(normal)
    db.session.commit()
    job, _workspace = _job(creador=_usuario("tester"))

    client.post("/login", data={"username": "normal", "password": "clave"})
    respuesta = client.post(f"/jobs/{job.id}/eliminar")

    assert respuesta.status_code == 403
    assert db.session.get(Job, job.id) is not None


def test_servicio_rechaza_trabajo_activo(app):
    job, _workspace = _job(status="queued")

    try:
        eliminar_trabajo(job)
    except JobNoEliminable:
        pass
    else:  # pragma: no cover - el test debe fallar si no lanza
        raise AssertionError("debía rechazar el trabajo activo")

    assert db.session.get(Job, job.id) is not None


def test_comando_delete_job(app):
    job, workspace = _job()
    runner = app.test_cli_runner()

    resultado = runner.invoke(args=["delete-job", job.id])

    assert resultado.exit_code == 0, resultado.output
    assert db.session.get(Job, job.id) is None
    assert not workspace.exists()


def test_boton_eliminar_aparece_para_terminados(client, login):
    login()
    job, _workspace = _job()

    respuesta = client.get("/")

    assert respuesta.status_code == 200
    html = respuesta.get_data(as_text=True)
    assert f'data-job-url="/jobs/{job.id}/eliminar"' in html
    assert "Eliminar" in html
