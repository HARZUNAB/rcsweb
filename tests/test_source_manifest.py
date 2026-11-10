"""Pruebas del manifiesto de fuentes y los formularios dinámicos."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app.domain.catalogs import manifest
from app.extensions import db
from app.models import Job, JobSource, User, nuevo_uuid
from app.services import panels, plots
from app.services.workspace import crear_workspace, ruta_workspace

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def _manifiesto(tmp_path: Path, monkeypatch) -> Path:
    ruta = tmp_path / "sources.json"
    ruta.write_text(
        json.dumps(
            {
                "version": 1,
                "sources": [
                    {
                        "id": "ref_x",
                        "label": "Referencia X",
                        "role": "reference",
                        "format": "eventquery",
                        "description": "Referencia de prueba",
                        "accept": [".csv"],
                        "validator": "eventquery",
                        "download_handler": "eventquery",
                    },
                    {
                        "id": "local_a",
                        "label": "Local A",
                        "role": "local",
                        "format": "seiscomp",
                        "description": "Fuente local A",
                        "accept": [".csv"],
                        "validator": "seiscomp",
                        "download_handler": "seiscomp",
                        "requires_radius": True,
                        "default_primary": True,
                        "visible_in_observaciones": True,
                    },
                    {
                        "id": "local_b",
                        "label": "Local B",
                        "role": "local",
                        "format": "seisan",
                        "description": "Fuente local B",
                        "accept": [".out", ".txt", ".dat"],
                        "validator": "seisan",
                        "download_handler": "seisan",
                        "visible_in_observaciones": True,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CATALOG_SOURCES_MANIFEST", str(ruta))
    return ruta


def _job() -> Job:
    job = Job(
        id=nuevo_uuid(),
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 31, tzinfo=UTC),
        status="done",
        created_by_id=db.session.execute(
            db.select(User.id).filter_by(username="tester")
        ).scalar_one(),
    )
    db.session.add(job)
    db.session.commit()
    crear_workspace(job.id)
    return job


def test_manifiesto_resuelve_roles_y_etiquetas(tmp_path, monkeypatch):
    _manifiesto(tmp_path, monkeypatch)

    assert manifest.referencia().id == "ref_x"
    assert [fuente.id for fuente in manifest.locales()] == ["local_a", "local_b"]
    assert manifest.etiqueta("local_a") == "Local A"
    assert manifest.default_primary() == "local_a"


def test_subida_muestra_fuentes_del_manifiesto(client, login, tmp_path, monkeypatch):
    _manifiesto(tmp_path, monkeypatch)
    login()

    html = client.get("/jobs/new").get_data(as_text=True)

    assert "Referencia X" in html
    assert "Local A" in html
    assert "Local B" in html
    assert 'name="incluir_local_a"' in html
    assert 'name="local_a"' in html
    assert 'name="incluir_seiscomp"' not in html


def test_solicitud_muestra_fuentes_del_manifiesto(client, login, tmp_path, monkeypatch):
    _manifiesto(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "app.blueprints.solicitudes.seiscomp_configurada", lambda: False
    )
    login()

    html = client.get("/solicitudes/nueva").get_data(as_text=True)

    assert "Local A" in html
    assert "Local B" in html
    assert 'name="incluir_local_a"' in html
    assert 'name="incluir_seiscomp"' not in html
    assert "Referencia X" in html


def test_alta_con_fuente_nueva(client, login, sin_celery, tmp_path, monkeypatch):
    _manifiesto(tmp_path, monkeypatch)
    login()
    datos = {
        "period_start": "2026-10-01",
        "period_end": "2026-10-31",
        "incluir_local_a": "y",
        "primary_source": "local_a",
        "alias_local_a": "Local A corregida",
        "ref_x": (
            open(SAMPLES / "eventquery_20261001000000_20261031235959.csv", "rb"),
            "eventquery.csv",
        ),
        "local_a": (
            open(SAMPLES / "seiscomp_20261001000000_20261031235959.csv", "rb"),
            "seiscomp.csv",
        ),
    }

    respuesta = client.post(
        "/jobs/new", data=datos, content_type="multipart/form-data"
    )

    assert respuesta.status_code == 302
    job = db.session.execute(db.select(Job)).scalar_one()
    fuentes = {
        fuente.kind: fuente for fuente in job.sources
    }
    assert set(fuentes) == {"ref_x", "local_a"}
    assert fuentes["ref_x"].role == "referencia"
    assert fuentes["local_a"].alias == "Local A corregida"
    assert {archivo.kind for archivo in job.files} == {"ref_x", "local_a"}


def test_paneles_usa_fuentes_locales_del_manifiesto(
    client, login, tmp_path, monkeypatch
):
    _manifiesto(tmp_path, monkeypatch)
    job = _job()
    workspace = ruta_workspace(job.id)
    resultados = workspace / "resultados"
    resultados.mkdir(parents=True, exist_ok=True)
    (resultados / "no_publicados_local_a.csv").write_text(
        "Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista\n"
        "2026-10-01 00:00:00,-30.0,-71.0,30.0,3.0,ML,ana\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        panels, "_asignar", lambda eventos: (eventos, [])
    )
    monkeypatch.setattr(plots, "_perfiles", lambda: [])
    login()

    html = client.get(
        f"/jobs/{job.id}/paneles",
        query_string={"dataset": "observaciones"},
    ).get_data(as_text=True)

    assert "fuente=local_a" in html
    assert "fuente=local_b" in html
    assert "fuente=ref_x" not in html


def test_solicitud_con_fuente_nueva(client, login, tmp_path, monkeypatch):
    _manifiesto(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "app.blueprints.solicitudes.seiscomp_configurada", lambda: True
    )
    monkeypatch.setattr(
        "app.blueprints.solicitudes.encolar_solicitud", lambda *_: None
    )
    login()

    respuesta = client.post(
        "/solicitudes/nueva",
        data={
            "period_start": "01/10/2026",
            "period_end": "31/10/2026",
            "server": "10.54.217.9",
            "remote_user": "sysopr",
            "password": "secreto",
            "incluir_local_a": "y",
            "alias_local_a": "Local A octubre",
            "radio_km": "600",
            "primary_source": "local_a",
        },
    )

    assert respuesta.status_code == 302
    from app.models import CatalogRequest

    solicitud = db.session.execute(db.select(CatalogRequest)).scalar_one()
    assert solicitud.primary_source == "local_a"
    assert solicitud.station_radius_km == 600
    archivos = {archivo.kind: archivo for archivo in solicitud.files}
    assert set(archivos) == {"ref_x", "local_a"}
    assert archivos["local_a"].display_name == "Local A octubre"


def _manifiesto_extra(tmp_path, monkeypatch, sources):
    ruta = tmp_path / "sources_extra.json"
    ruta.write_text(json.dumps({"version": 1, "sources": sources}), encoding="utf-8")
    monkeypatch.setenv("CATALOG_SOURCES_MANIFEST", str(ruta))
    return ruta


def test_validar_rechaza_dos_referencias(tmp_path, monkeypatch):
    _manifiesto_extra(
        tmp_path,
        monkeypatch,
        [
            {
                "id": "ref_a",
                "label": "Ref A",
                "role": "reference",
                "format": "eventquery",
                "validator": "eventquery",
                "download_handler": "eventquery",
            },
            {
                "id": "ref_b",
                "label": "Ref B",
                "role": "reference",
                "format": "eventquery",
                "validator": "eventquery",
                "download_handler": "eventquery",
            },
            {
                "id": "local_a",
                "label": "Local A",
                "role": "local",
                "format": "seiscomp",
                "validator": "seiscomp",
            },
        ],
    )

    import pytest

    with pytest.raises(manifest.ManifestError) as exc:
        manifest.validar()
    assert "exactamente una" in str(exc.value)


def test_validar_rechaza_formato_desconocido(tmp_path, monkeypatch):
    _manifiesto_extra(
        tmp_path,
        monkeypatch,
        [
            {
                "id": "ref_x",
                "label": "Ref X",
                "role": "reference",
                "format": "eventquery",
                "validator": "eventquery",
                "download_handler": "eventquery",
            },
            {
                "id": "local_x",
                "label": "Local X",
                "role": "local",
                "format": "formato_inexistente",
                "validator": "seiscomp",
            },
        ],
    )

    import pytest

    with pytest.raises(manifest.ManifestError) as exc:
        manifest.validar()
    assert "formato desconocido" in str(exc.value)


def test_cli_sources_validate_ok(app):
    resultado = app.test_cli_runner().invoke(args=["sources", "validate"])

    assert resultado.exit_code == 0
    assert "Manifiesto válido" in resultado.output


def test_cli_sources_validate_invalido(app, tmp_path, monkeypatch):
    _manifiesto_extra(
        tmp_path,
        monkeypatch,
        [
            {
                "id": "only_local",
                "label": "Solo local",
                "role": "local",
                "format": "seiscomp",
                "validator": "seiscomp",
            }
        ],
    )

    resultado = app.test_cli_runner().invoke(args=["sources", "validate"])

    assert resultado.exit_code == 1
    assert "ERROR" in resultado.output


def test_create_app_rechaza_manifiesto_invalido(tmp_path, monkeypatch):
    _manifiesto_extra(
        tmp_path,
        monkeypatch,
        [
            {
                "id": "only_local",
                "label": "Solo local",
                "role": "local",
                "format": "seiscomp",
                "validator": "seiscomp",
            }
        ],
    )

    import pytest

    from app import create_app
    from app.config import TestConfig

    with pytest.raises(manifest.ManifestError):
        create_app(TestConfig)


def _manifiesto_con_fuente_sin_archivo(tmp_path, monkeypatch, extraction_name="central_{inicio}_{fin}.csv"):
    return _manifiesto_extra(
        tmp_path,
        monkeypatch,
        [
            {
                "id": "ref_x",
                "label": "Referencia X",
                "role": "reference",
                "format": "eventquery",
                "validator": "eventquery",
                "download_handler": "eventquery",
            },
            {
                "id": "central_tmp",
                "label": "Central de prueba",
                "role": "local",
                "format": "local_db",
                "validator": "central",
                "requires_file": False,
                "extraction_name": extraction_name,
                "dsn_env": "RCS_CENTRAL_DSN",
                "default_primary": True,
            },
        ],
    )


def test_fuente_sin_archivo_sugiere_nombre_de_extraccion(
    tmp_path, monkeypatch
):
    _manifiesto_con_fuente_sin_archivo(tmp_path, monkeypatch)

    fuente = manifest.por_id("central_tmp")

    assert fuente is not None
    assert fuente.requires_file is False
    assert (
        fuente.nombre_extraccion("20261001", "20261031")
        == "central_20261001_20261031.csv"
    )


def test_formulario_oculta_archivo_para_fuente_sin_archivo(
    client, login, tmp_path, monkeypatch
):
    _manifiesto_con_fuente_sin_archivo(tmp_path, monkeypatch)
    login()

    html = client.get("/jobs/new").get_data(as_text=True)

    assert "Nuevo trabajo" in html
    assert "No requiere archivo." in html
    assert 'name="central_tmp"' not in html
    assert "central_{inicio}_{fin}.csv" in html


def test_alta_con_fuente_sin_archivo(
    client, login, sin_celery, tmp_path, monkeypatch
):
    _manifiesto_con_fuente_sin_archivo(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "app.domain.catalogs.adapters.central.Adaptador.validar_periodo",
        lambda self, job, rango=None: {
            "codigo": "central_tmp",
            "ok": True,
            "errores": [],
            "advertencias": [],
            "eventos": 1,
            "desde": None,
            "hasta": None,
        },
    )
    login()
    datos = {
        "period_start": "2026-10-01",
        "period_end": "2026-10-31",
        "incluir_central_tmp": "y",
        "primary_source": "central_tmp",
        "alias_central_tmp": "Central octubre",
        "ref_x": (
            open(SAMPLES / "eventquery_20261001000000_20261031235959.csv", "rb"),
            "eventquery.csv",
        ),
    }

    respuesta = client.post(
        "/jobs/new", data=datos, content_type="multipart/form-data"
    )

    assert respuesta.status_code == 302
    job = db.session.execute(db.select(Job)).scalar_one()
    assert job.status == "queued"
    assert {fuente.kind for fuente in job.sources} == {"ref_x", "central_tmp"}
    assert {archivo.kind for archivo in job.files} == {"ref_x"}
    central = db.session.execute(
        db.select(JobSource).filter_by(job_id=job.id, kind="central_tmp")
    ).scalar_one()
    assert central.role == "local_principal"
    assert central.alias == "Central octubre"
    assert sin_celery == [job.id]


def test_validar_rechaza_extraccion_con_ruta(tmp_path, monkeypatch):
    import pytest

    _manifiesto_con_fuente_sin_archivo(
        tmp_path, monkeypatch, extraction_name="carpeta/central.csv"
    )

    with pytest.raises(manifest.ManifestError) as exc:
        manifest.validar()

    assert "extraction_name con ruta" in str(exc.value)


def _manifiesto_con_central_y_archivo(tmp_path, monkeypatch):
    return _manifiesto_extra(
        tmp_path,
        monkeypatch,
        [
            {
                "id": "ref_x",
                "label": "Referencia X",
                "role": "reference",
                "format": "eventquery",
                "validator": "eventquery",
                "download_handler": "eventquery",
            },
            {
                "id": "local_a",
                "label": "Local A",
                "role": "local",
                "format": "local_export",
                "validator": "seiscomp",
                "accept": [".csv"],
                "download_handler": "seiscomp",
                "default_primary": True,
            },
            {
                "id": "central_tmp",
                "label": "Central de prueba",
                "role": "local",
                "format": "local_db",
                "validator": "central",
                "requires_file": False,
                "extraction_name": "central_{inicio}_{fin}.csv",
                "dsn_env": "RCS_CENTRAL_DSN",
            },
        ],
    )


def test_rango_de_fechas_en_la_tarjeta(client, login, tmp_path, monkeypatch):
    _manifiesto_con_fuente_sin_archivo(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "app.domain.catalogs.adapters.central.Adaptador.disponibilidad",
        lambda self, usuario=None: {
            "desde": datetime(1982, 9, 18, tzinfo=UTC),
            "hasta": datetime(2025, 3, 31, tzinfo=UTC),
        },
    )
    login()

    html = client.get("/jobs/new").get_data(as_text=True)

    assert "Rango disponible en la base" in html
    assert "18/09/1982" in html
    assert "31/03/2025" in html
    assert 'data-rango-fuente="central_tmp"' in html


def test_rango_no_disponible_no_rompe_el_formulario(
    client, login, tmp_path, monkeypatch
):
    _manifiesto_con_fuente_sin_archivo(tmp_path, monkeypatch)

    def _falla(self, usuario=None):
        raise RuntimeError("sin conexión")

    monkeypatch.setattr(
        "app.domain.catalogs.adapters.central.Adaptador.disponibilidad",
        _falla,
    )
    login()

    html = client.get("/jobs/new").get_data(as_text=True)

    assert "Nuevo trabajo" in html
    assert "No se pudo consultar el rango disponible" in html


def test_sin_eventos_en_la_unica_fuente_deja_borrador(
    client, login, sin_celery, tmp_path, monkeypatch
):
    _manifiesto_con_fuente_sin_archivo(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "app.domain.catalogs.adapters.central.Adaptador.validar_periodo",
        lambda self, job, rango=None: {
            "codigo": "central_tmp",
            "ok": True,
            "errores": [],
            "advertencias": [
                "La base central no tiene eventos en el período seleccionado."
            ],
            "eventos": 0,
            "desde": None,
            "hasta": None,
        },
    )
    login()
    datos = {
        "period_start": "2026-10-01",
        "period_end": "2026-10-31",
        "incluir_central_tmp": "y",
        "primary_source": "central_tmp",
        "ref_x": (
            open(SAMPLES / "eventquery_20261001000000_20261031235959.csv", "rb"),
            "eventquery.csv",
        ),
    }

    respuesta = client.post(
        "/jobs/new", data=datos, content_type="multipart/form-data"
    )

    assert respuesta.status_code == 302
    job = db.session.execute(db.select(Job)).scalar_one()
    assert job.status == "draft"
    central = db.session.execute(
        db.select(JobSource).filter_by(job_id=job.id, kind="central_tmp")
    ).scalar_one()
    assert central.status == "error"
    assert "única fuente local" in (central.message or "")
    assert sin_celery == []


def test_sin_eventos_con_otra_fuente_encola(
    client, login, sin_celery, tmp_path, monkeypatch
):
    _manifiesto_con_central_y_archivo(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "app.domain.catalogs.adapters.central.Adaptador.validar_periodo",
        lambda self, job, rango=None: {
            "codigo": "central_tmp",
            "ok": True,
            "errores": [],
            "advertencias": [
                "La base central no tiene eventos en el período seleccionado."
            ],
            "eventos": 0,
            "desde": None,
            "hasta": None,
        },
    )
    login()
    datos = {
        "period_start": "2026-10-01",
        "period_end": "2026-10-31",
        "incluir_local_a": "y",
        "incluir_central_tmp": "y",
        "primary_source": "local_a",
        "alias_local_a": "Local A",
        "ref_x": (
            open(SAMPLES / "eventquery_20261001000000_20261031235959.csv", "rb"),
            "eventquery.csv",
        ),
        "local_a": (
            open(SAMPLES / "seiscomp_20261001000000_20261031235959.csv", "rb"),
            "seiscomp.csv",
        ),
    }

    respuesta = client.post(
        "/jobs/new", data=datos, content_type="multipart/form-data"
    )

    assert respuesta.status_code == 302
    job = db.session.execute(db.select(Job)).scalar_one()
    assert job.status == "queued"
    central = db.session.execute(
        db.select(JobSource).filter_by(job_id=job.id, kind="central_tmp")
    ).scalar_one()
    assert central.status == "ok"
    assert "no tiene eventos" in (central.message or "")
    assert {archivo.kind for archivo in job.files} == {"ref_x", "local_a"}
    assert sin_celery == [job.id]
