"""Prueba de integración del pipeline real.

Se salta si el proyecto base no está montado (por ejemplo en CI). En local
ejercita los scripts reales con el dataset de muestra.
"""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.domain.catalogs.canonical import leer_canonico
from app.extensions import db
from app.models import Job, JobFile, JobSource, nuevo_uuid
from app.services.detail import leer_filas
from app.services.pipeline import ejecutar_pipeline
from app.services.plots import generar_mapa, generar_miniatura
from app.services.results import cargar_indice, leer_tabla
from app.services.workspace import crear_workspace, nombre_entrada

RAIZ = Path(__file__).resolve().parent.parent
SAMPLES = RAIZ / "samples"


def _buscar_core() -> Path | None:
    candidatos = [
        os.environ.get("RCS_CORE_PATH"),
        "/opt/rcs-core",
        str(Path.home() / "Desarrollo/revisacatalogosweb"),
    ]
    for candidato in candidatos:
        if not candidato:
            continue
        ruta = Path(candidato)
        if (ruta / "compara.py").is_file():
            return ruta
    return None


CORE = _buscar_core()

pytestmark = pytest.mark.skipif(
    CORE is None or not (SAMPLES / "select.out").is_file(),
    reason="requiere el proyecto base montado y el dataset de muestra",
)


def test_pipeline_completo_con_muestra(app, tmp_path):
    app.config["RCS_CORE_PATH"] = CORE

    with app.app_context():
        job = Job(
            id=nuevo_uuid(),
            period_start=datetime(2026, 10, 1, tzinfo=UTC),
            period_end=datetime(2026, 10, 31, 23, 59, 59, tzinfo=UTC),
            status="queued",
        )
        db.session.add(job)
        db.session.commit()
        workspace = crear_workspace(job.id)

        for kind, nombre in (
            ("seisan", "select.out"),
            ("eventquery", "eventquery_20261001000000_20261031235959.csv"),
            ("seiscomp", "seiscomp_20261001000000_20261031235959.csv"),
        ):
            destino = workspace / "inputs" / nombre_entrada(kind, nombre)
            shutil.copy2(SAMPLES / nombre, destino)
            db.session.add(
                JobFile(
                    job_id=job.id,
                    kind=kind,
                    original_name=nombre,
                    stored_name=f"inputs/{nombre_entrada(kind, nombre)}",
                    size=destino.stat().st_size,
                )
            )
        db.session.commit()

        resultado = ejecutar_pipeline(job.id)
        assert resultado["estado"] == "done"

        db.session.expire_all()
        job = db.session.get(Job, job.id)
        assert job.status == "done"
        assert job.progress == 100
        assert job.error is None
        assert len(job.steps) == 10
        assert all(paso.status == "done" for paso in job.steps)
        assert len(job.artifacts) >= 20

        indice = cargar_indice(workspace)
        assert indice["no_publicados"]["seisan"]["filas"] == 1
        assert indice["no_publicados"]["seiscomp"]["filas"] == 2
        assert indice["no_actualizados"]["seisan"]["filas"] == 1
        assert indice["no_actualizados"]["seiscomp"]["filas"] == 1
        assert indice["repetidos"]["publica_estricto"]["filas"] == 2
        assert indice["catalogos"]["seisan"]["filas"] == 3

        assert len(leer_canonico(workspace, "eventquery")) == 4
        assert len(leer_canonico(workspace, "seisan")) == 3
        assert len(leer_canonico(workspace, "seiscomp")) == 4

        no_act = leer_tabla(workspace, "no_actualizados_seisan.csv")
        assert "revision" in no_act["columnas"]
        assert "publicacion_probable" in no_act["columnas"]
        assert no_act["filas"][0]["revision"] in {"Alta", "Media", "Baja"}
        assert no_act["filas"][0]["publicacion_probable"]
        assert "_fila" in no_act["filas"][0]

        repetidos = leer_tabla(workspace, "repetidos_publica_estricto.csv")
        assert "analista_seisan" in repetidos["columnas"]
        assert "analista_seiscomp" in repetidos["columnas"]
        assert any(fila.get("analista_seisan") for fila in repetidos["filas"])

        leido = leer_filas(workspace, "no_publicados_seisan.csv")
        assert leido is not None
        _columnas, filas_no_pub = leido
        miniatura = generar_miniatura(
            workspace,
            "no_publicados",
            "no_publicados_seisan.csv",
            filas_no_pub,
            0,
        )
        assert miniatura.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(miniatura) > 1000

        mapa = generar_mapa(
            workspace,
            "no_publicados",
            "seisan",
            "no_publicados_seisan.csv",
            filas_no_pub,
            0,
        )
        assert mapa.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(mapa) > 20000


def test_pipeline_solo_seiscomp(app, tmp_path):
    app.config["RCS_CORE_PATH"] = CORE

    with app.app_context():
        job = Job(
            id=nuevo_uuid(),
            period_start=datetime(2026, 10, 1, tzinfo=UTC),
            period_end=datetime(2026, 10, 31, 23, 59, 59, tzinfo=UTC),
            status="queued",
            origin="upload",
        )
        db.session.add(job)
        db.session.commit()
        workspace = crear_workspace(job.id)

        for kind, nombre in (
            ("eventquery", "eventquery_20261001000000_20261031235959.csv"),
            ("seiscomp", "seiscomp_20261001000000_20261031235959.csv"),
        ):
            destino = workspace / "inputs" / nombre_entrada(kind, nombre)
            shutil.copy2(SAMPLES / nombre, destino)
            db.session.add(
                JobFile(
                    job_id=job.id,
                    kind=kind,
                    original_name=nombre,
                    stored_name=f"inputs/{nombre_entrada(kind, nombre)}",
                    size=destino.stat().st_size,
                )
            )
        db.session.add(JobSource(job_id=job.id, kind="eventquery", role="referencia"))
        db.session.add(JobSource(job_id=job.id, kind="seiscomp", role="local_principal"))
        db.session.commit()

        resultado = ejecutar_pipeline(job.id)
        assert resultado["estado"] == "done"

        db.session.expire_all()
        job = db.session.get(Job, job.id)
        assert job.status == "done"
        assert [paso.script for paso in sorted(job.steps, key=lambda p: p.orden)] == [
            "normalizar_eventquery",
            "convertir_seiscomp",
            "comparar_seiscomp",
            "detectar_repetidos",
        ]
        assert all(paso.status == "done" for paso in job.steps)

        indice = cargar_indice(workspace)
        assert set(indice["no_publicados"]) == {"seiscomp"}
        assert set(indice["no_actualizados"]) == {"seiscomp"}
        assert indice["no_publicados"]["seiscomp"]["filas"] == 2
        assert indice["no_actualizados"]["seiscomp"]["filas"] == 1
        assert "seisan" not in indice["catalogos"]
        assert len(leer_canonico(workspace, "eventquery")) == 4
        assert len(leer_canonico(workspace, "seiscomp")) == 4
        assert leer_canonico(workspace, "seisan") == []
        assert (workspace / "resultados/repetidos_seiscomp_estricto.csv").is_file()
        assert not (workspace / "informes/rep_seisan_estricto.txt").exists()
