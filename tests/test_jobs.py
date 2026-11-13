"""Pruebas del alta, seguimiento y descargas de trabajos."""

from __future__ import annotations

from datetime import UTC, datetime

from app.extensions import db
from app.models import Job, JobArtifact, JobFile, JobSource, JobStep, nuevo_uuid
from app.services.workspace import crear_workspace


def _datos_formulario(samples):
    return {
        "period_start": "2026-10-01",
        "period_end": "2026-10-31",
        "incluir_seisan": "y",
        "primary_source": "seisan",
        "alias_seisan": "Fuente secundaria",
        "seisan": (open(samples / "select.out", "rb"), "select.out"),
        "eventquery": (
            open(samples / "eventquery_20261001000000_20261031235959.csv", "rb"),
            "eventquery.csv",
        ),
    }


def test_nuevo_requiere_login(client):
    respuesta = client.get("/jobs/new")

    assert respuesta.status_code == 302
    assert "/login" in respuesta.headers["Location"]


def test_pagina_subida_es_secundaria(client, login):
    login()

    html = client.get("/jobs/new/subir").get_data(as_text=True)

    assert "Subir catálogos" in html
    assert "La forma habitual es descargar los catálogos del servidor" in html
    assert 'href="/solicitudes/nueva"' in html


def test_subida_no_muestra_jerga_de_transporte(client, login):
    login()

    html = client.get("/jobs/new/subir").get_data(as_text=True)

    assert "SSH" not in html
    assert "SCP" not in html


def test_crear_trabajo_encola_y_guarda_archivos(client, login, samples, sin_celery):
    login()
    datos = _datos_formulario(samples)

    respuesta = client.post("/jobs/new/subir", data=datos, content_type="multipart/form-data")

    assert respuesta.status_code == 302
    job = db.session.execute(db.select(Job)).scalar_one()
    assert job.status == "queued"
    assert job.inicio14 == "20261001000000"
    assert job.fin14 == "20261031235959"
    assert len(job.files) == 2
    assert {f.kind for f in job.files} == {"seisan", "eventquery"}
    for archivo in job.files:
        assert archivo.size > 0
        assert archivo.sha256
    assert {source.kind for source in job.sources} == {"eventquery", "seisan"}
    assert {source.role for source in job.sources} == {
        "referencia",
        "local_principal",
    }
    assert all(source.format for source in job.sources)
    assert all(source.alias for source in job.sources)
    assert sin_celery == [job.id]
    assert respuesta.headers["Location"].endswith(f"/jobs/{job.id}")


def test_crear_trabajo_seiscomp_por_defecto(client, login, samples, sin_celery):
    login()
    datos = {
        "period_start": "2026-10-01",
        "period_end": "2026-10-31",
        "incluir_seiscomp": "y",
        "primary_source": "seiscomp",
        "alias_seiscomp": "Fuente principal",
        "seiscomp": (
            open(samples / "seiscomp_20261001000000_20261031235959.csv", "rb"),
            "seiscomp.csv",
        ),
        "eventquery": (
            open(samples / "eventquery_20261001000000_20261031235959.csv", "rb"),
            "eventquery.csv",
        ),
    }

    client.post("/jobs/new/subir", data=datos, content_type="multipart/form-data")

    job = db.session.execute(db.select(Job)).scalar_one()
    assert job.status == "queued"
    roles = {source.kind: source.role for source in job.sources}
    assert roles == {"eventquery": "referencia", "seiscomp": "local_principal"}
    assert {source.alias for source in job.sources} == {
        "Eventquery",
        "Fuente principal",
    }
    assert {archivo.kind for archivo in job.files} == {"eventquery", "seiscomp"}


def test_sin_fuente_local_no_crea_trabajo(client, login, samples, sin_celery):
    login()
    datos = {
        "period_start": "2026-10-01",
        "period_end": "2026-10-31",
        "eventquery": (
            open(samples / "eventquery_20261001000000_20261031235959.csv", "rb"),
            "eventquery.csv",
        ),
    }

    respuesta = client.post("/jobs/new/subir", data=datos, content_type="multipart/form-data")

    assert respuesta.status_code == 200
    assert "al menos una fuente local" in respuesta.get_data(as_text=True)
    assert db.session.execute(db.select(Job)).scalar_one_or_none() is None


def test_validacion_invalida_deja_trabajo_en_borrador(client, login, samples, sin_celery, tmp_path):
    login()
    malo = tmp_path / "eventquery_invalido.csv"
    malo.write_text("a,b\n1,2\n", encoding="utf-8")
    datos = {
        "period_start": "2026-10-01",
        "period_end": "2026-10-31",
        "incluir_seisan": "y",
        "primary_source": "seisan",
        "alias_seisan": "Fuente secundaria",
        "seisan": (open(samples / "select.out", "rb"), "select.out"),
        "eventquery": (open(malo, "rb"), "eventquery_invalido.csv"),
    }

    respuesta = client.post("/jobs/new/subir", data=datos, content_type="multipart/form-data")

    assert respuesta.status_code == 302
    job = db.session.execute(db.select(Job)).scalar_one()
    assert job.status == "draft"
    assert "Validación fallida" in (job.current_step or "")
    assert sin_celery == []
    source = db.session.execute(
        db.select(JobSource).filter_by(job_id=job.id, kind="eventquery")
    ).scalar_one()
    assert source.status == "error"
    assert "columnas" in (source.message or "").lower()


def test_periodo_invalido_no_crea_trabajo(client, login, samples, sin_celery):
    login()
    datos = _datos_formulario(samples)
    datos["period_end"] = "2026-09-01"

    respuesta = client.post("/jobs/new/subir", data=datos, content_type="multipart/form-data")

    assert respuesta.status_code == 200
    assert "posterior" in respuesta.get_data(as_text=True)
    assert db.session.execute(db.select(Job)).scalar_one_or_none() is None


def test_cancelar_trabajo_en_cola(client, login):
    login()
    job = Job(
        id=nuevo_uuid(),
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 31, tzinfo=UTC),
        status="queued",
    )
    db.session.add(job)
    db.session.commit()

    respuesta = client.post(f"/jobs/{job.id}/cancelar")

    assert respuesta.status_code == 302
    db.session.expire_all()
    assert db.session.get(Job, job.id).status == "cancelled"


def test_estado_devuelve_la_pagina_para_htmx(client, login):
    login()
    job = Job(
        id=nuevo_uuid(),
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 31, tzinfo=UTC),
        status="running",
        progress=42,
        current_step="Comparando",
    )
    db.session.add(job)
    db.session.commit()

    respuesta = client.get(f"/jobs/{job.id}/estado")

    assert respuesta.status_code == 200
    html = respuesta.get_data(as_text=True)
    assert 'id="job-page"' in html
    assert "42%" in html


def test_descarga_valida_y_bloquea_traversal(app, client, login):
    login()
    job = Job(
        id=nuevo_uuid(),
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 31, tzinfo=UTC),
        status="done",
    )
    db.session.add(job)
    db.session.commit()
    workspace = crear_workspace(job.id)
    (workspace / "resultados").mkdir(parents=True, exist_ok=True)
    (workspace / "resultados" / "ok.csv").write_text("a,b\n1,2\n", encoding="utf-8")

    bueno = JobArtifact(job_id=job.id, tipo="resultado", ruta="resultados/ok.csv", size=8)
    malo = JobArtifact(job_id=job.id, tipo="resultado", ruta="../fuera.csv", size=8)
    db.session.add_all([bueno, malo])
    db.session.commit()

    respuesta = client.get(f"/jobs/{job.id}/descargar/{bueno.id}")
    assert respuesta.status_code == 200
    assert "attachment" in respuesta.headers["Content-Disposition"]

    respuesta = client.get(f"/jobs/{job.id}/descargar/{malo.id}")
    assert respuesta.status_code == 404


def test_periodo_se_guarda_en_utc(client, login, samples, sin_celery):
    login()
    datos = _datos_formulario(samples)

    client.post("/jobs/new/subir", data=datos, content_type="multipart/form-data")

    job = db.session.execute(db.select(Job)).scalar_one()
    assert job.period_start.day == 1
    assert job.period_end.hour == 23
    assert job.period_end.minute == 59
    assert len(db.session.execute(db.select(JobFile)).scalars().all()) == 2


def test_detalle_muestra_advertencias_de_fuentes(client, login):
    login()
    job = Job(
        id=nuevo_uuid(),
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 31, tzinfo=UTC),
        status="queued",
        current_step="En cola",
    )
    db.session.add(job)
    db.session.add(
        JobSource(
            job_id=job.id,
            kind="central",
            alias="Central",
            format="local_db",
            role="local_principal",
            status="ok",
            message=(
                "La base central no tiene eventos en el período seleccionado."
            ),
        )
    )
    db.session.commit()

    html = client.get(f"/jobs/{job.id}").get_data(as_text=True)

    assert "Advertencias de fuentes" in html
    assert "no tiene eventos" in html


def test_reanalizar_reencola_y_limpia(client, login, sin_celery):
    login()
    job = Job(
        id=nuevo_uuid(),
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 31, tzinfo=UTC),
        status="done",
        progress=100,
        current_step="Terminado",
    )
    db.session.add(job)
    db.session.commit()
    workspace = crear_workspace(job.id)
    (workspace / "inputs").mkdir(exist_ok=True)
    (workspace / "inputs" / "entrada.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    for nombre in ("resultados", "paneles", "plots", "logs", "datos"):
        carpeta = workspace / nombre
        carpeta.mkdir(exist_ok=True)
        (carpeta / "archivo.txt").write_text("x", encoding="utf-8")
    db.session.add(
        JobStep(
            job_id=job.id,
            orden=1,
            script="paso",
            status="done",
            log_path="logs/pipeline.log",
        )
    )
    db.session.add(
        JobArtifact(
            job_id=job.id,
            tipo="resultado",
            ruta="resultados/archivo.txt",
            size=1,
        )
    )
    db.session.commit()

    respuesta = client.post(f"/jobs/{job.id}/reanalizar")

    assert respuesta.status_code == 302
    job = db.session.get(Job, job.id)
    assert job.status == "queued"
    assert job.progress == 0
    assert job.current_step == "En cola"
    assert job.error is None
    assert sin_celery == [job.id]
    assert (
        db.session.execute(db.select(JobStep).filter_by(job_id=job.id))
        .scalars()
        .all()
        == []
    )
    assert (
        db.session.execute(db.select(JobArtifact).filter_by(job_id=job.id))
        .scalars()
        .all()
        == []
    )
    assert (workspace / "inputs" / "entrada.csv").is_file()
    for nombre in ("resultados", "paneles", "plots", "logs", "datos"):
        assert not (workspace / nombre).exists()


def test_reanalizar_rechaza_trabajo_en_curso(client, login, sin_celery):
    login()
    job = Job(
        id=nuevo_uuid(),
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 31, tzinfo=UTC),
        status="running",
        progress=42,
        current_step="Paso en curso",
    )
    db.session.add(job)
    db.session.commit()

    respuesta = client.post(
        f"/jobs/{job.id}/reanalizar", follow_redirects=True
    )

    assert respuesta.status_code == 200
    assert "en curso" in respuesta.get_data(as_text=True)
    assert db.session.get(Job, job.id).status == "running"
    assert sin_celery == []


def test_detalle_muestra_reanalizar_solo_si_corresponde(client, login):
    login()
    job = Job(
        id=nuevo_uuid(),
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 31, tzinfo=UTC),
        status="done",
    )
    db.session.add(job)
    db.session.commit()

    html = client.get(f"/jobs/{job.id}").get_data(as_text=True)
    assert "Re-analizar" in html
    assert 'id="modalReanalizar"' in html

    job.status = "running"
    db.session.commit()
    html = client.get(f"/jobs/{job.id}").get_data(as_text=True)
    assert "Re-analizar" not in html
    assert 'id="modalReanalizar"' not in html


def test_detalle_valida_fuente_directa_sin_mensaje(
    app, client, login, monkeypatch
):
    from app.services import source_status

    login()
    job = Job(
        id=nuevo_uuid(),
        period_start=datetime(2026, 11, 1, tzinfo=UTC),
        period_end=datetime(2026, 11, 12, 23, 59, 59, tzinfo=UTC),
        status="done",
        current_step="Terminado",
    )
    db.session.add(job)
    source = JobSource(
        job_id=job.id,
        kind="central",
        alias="Central",
        format="local_db",
        role="local_secundaria",
        status="ok",
    )
    db.session.add(source)
    db.session.commit()

    class _Falso:
        source_id = ""

        def validar_periodo(self, job, rango=None):
            return {
                "ok": True,
                "errores": [],
                "advertencias": [
                    "La base central no tiene eventos en el período seleccionado."
                ],
                "eventos": 0,
            }

    monkeypatch.setattr(
        source_status, "obtener_adaptador", lambda formato: _Falso()
    )

    html = client.get(f"/jobs/{job.id}").get_data(as_text=True)

    assert "Advertencias de fuentes" in html
    assert "no tiene eventos" in html
    db.session.expire_all()
    source = db.session.get(JobSource, source.id)
    assert "no tiene eventos" in source.message


def test_jobs_new_redirige_a_solicitud(client, login):
    login()

    respuesta = client.get("/jobs/new")

    assert respuesta.status_code == 302
    assert respuesta.headers["Location"].endswith("/solicitudes/nueva")


def test_dashboard_muestra_descargas_en_curso(client, login):
    from app.models import CatalogRequest

    login()
    solicitud = CatalogRequest(
        id=nuevo_uuid(),
        mode="ssh",
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 31, 23, 59, 59, tzinfo=UTC),
        status="running",
        current_step="Descargando catálogos",
        server="10.54.217.9",
        remote_user="sysopr",
    )
    db.session.add(solicitud)
    db.session.commit()

    html = client.get("/").get_data(as_text=True)

    assert "Preparando catálogos" in html
    assert "Descargando catálogos" in html
    assert f"/solicitudes/{solicitud.id}" in html

    solicitud.status = "failed"
    solicitud.error = "Fallo de prueba"
    db.session.commit()

    html = client.get("/").get_data(as_text=True)
    assert "Descarga fallida" in html


def test_detalle_explica_pasos_omitidos(client, login):
    login()
    job = Job(
        id=nuevo_uuid(),
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 31, tzinfo=UTC),
        status="queued",
    )
    db.session.add(job)
    db.session.add_all(
        [
            JobStep(
                job_id=job.id,
                orden=1,
                script="revisar_excluidos",
                status="skipped",
            ),
            JobStep(
                job_id=job.id,
                orden=2,
                script="otro_paso",
                status="skipped",
            ),
            JobStep(
                job_id=job.id,
                orden=3,
                script="enriquecer_residuales",
                status="skipped",
            ),
        ]
    )
    db.session.commit()

    html = client.get(f"/jobs/{job.id}").get_data(as_text=True)

    assert "Omitido" in html
    assert "sin excluidos" in html
    assert "no aplica" in html
    assert "sin residuales" in html
