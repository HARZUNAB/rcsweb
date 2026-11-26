"""Pruebas de la ruta de análisis de señal de estaciones sin aportar."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime

from app.extensions import db
from app.models import Job, JobSource, User, nuevo_uuid
from app.services import indicios, picks_coverage
from app.services.workspace import crear_workspace, ruta_workspace


def _job() -> Job:
    job = Job(
        id=nuevo_uuid(),
        status="done",
        period_start=datetime(2026, 1, 1, tzinfo=UTC),
        period_end=datetime(2026, 1, 31, tzinfo=UTC),
    )
    db.session.add(job)
    db.session.add(
        JobSource(
            job_id=job.id,
            kind="seiscomp",
            alias="SeisComp",
            format="local_export",
            role="local_principal",
            priority=0,
            capabilities=["eventos", "arribos"],
        )
    )
    db.session.commit()
    crear_workspace(job.id)
    return job


def _reporte(job: Job, *, estado: str = "pendiente") -> None:
    destino = picks_coverage.ruta(ruta_workspace(job.id), "seiscomp")
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=picks_coverage.CAMPOS)
        escritor.writeheader()
        escritor.writerow(
            {
                "fuente": "seiscomp",
                "evento": "seiscomp:000001",
                "total_n": 1,
                "sin_picar_n": 1,
                "no_usadas_n": 0,
                "senal_estado": estado,
                "detalle": "[]",
            }
        )
    resumen = indicios.ruta_resumen(ruta_workspace(job.id))
    resumen.parent.mkdir(parents=True, exist_ok=True)
    resumen.write_text(
        json.dumps(
            {
                "esquema": indicios.ESQUEMA_INDICIOS,
                "total": {},
                "fuentes": {},
            }
        ),
        encoding="utf-8",
    )


def test_post_analizar_senal_encola(app, client, login, monkeypatch):
    job = _job()
    _reporte(job)
    app.config["RCS_DISPONIBILIDAD_URL"] = "http://sidecar:8010"
    llamadas = []

    class Tarea:
        id = "tarea-senal-1"

    def encolar(*argumentos, **opciones):
        llamadas.append((argumentos, opciones))
        return Tarea()

    monkeypatch.setattr(
        "app.blueprints.results.analizar_senal_picks_task.delay", encolar
    )
    login()
    respuesta = client.post(
        f"/jobs/{job.id}/indicios/senal",
        data={"fuente": "seiscomp"},
    )
    assert respuesta.status_code == 202
    datos = respuesta.get_json()
    assert datos["estado"] == "encolada"
    assert datos["task_id"] == "tarea-senal-1"
    assert datos["eventos"] == 1
    assert llamadas and llamadas[0][0][1] == "seiscomp"


def test_post_analizar_senal_sin_configuracion(app, client, login):
    job = _job()
    _reporte(job)
    app.config["RCS_DISPONIBILIDAD_URL"] = ""
    login()
    respuesta = client.post(
        f"/jobs/{job.id}/indicios/senal",
        data={"fuente": "seiscomp"},
    )
    assert respuesta.status_code == 503
    assert "no está configurada" in respuesta.get_json()["mensaje"]


def test_post_analizar_senal_sin_pendientes(app, client, login):
    job = _job()
    _reporte(job, estado="analizado")
    app.config["RCS_DISPONIBILIDAD_URL"] = "http://sidecar:8010"
    login()
    respuesta = client.post(
        f"/jobs/{job.id}/indicios/senal",
        data={"fuente": "seiscomp"},
    )
    assert respuesta.status_code == 400
    assert "señal pendiente" in respuesta.get_json()["mensaje"]


def test_post_analizar_senal_requiere_permiso(app, client, login):
    job = _job()
    _reporte(job)
    app.config["RCS_DISPONIBILIDAD_URL"] = "http://sidecar:8010"
    observador = User(username="observador", role="observador")
    observador.set_password("secret")
    db.session.add(observador)
    db.session.commit()
    client.post("/logout")
    client.post(
        "/login",
        data={"username": "observador", "password": "secret"},
    )
    respuesta = client.post(
        f"/jobs/{job.id}/indicios/senal",
        data={"fuente": "seiscomp"},
    )
    assert respuesta.status_code == 403


def test_solo_picks_no_entra_a_revision_prioritaria(app, client, login):
    job = _job()
    _reporte(job)
    login()
    por_defecto = client.get(
        f"/jobs/{job.id}/indicios",
        query_string={"fuente": "seiscomp"},
    )
    html_defecto = por_defecto.get_data(as_text=True)
    assert "No hay eventos para este filtro." in html_defecto
    assert "seiscomp:000001" not in html_defecto

    todos = client.get(
        f"/jobs/{job.id}/indicios",
        query_string={"fuente": "seiscomp", "alcance": "todos"},
    ).get_data(as_text=True)
    assert "seiscomp:000001" in todos
    assert "No aplica" in todos
    assert "Solo cobertura de picks" in todos


def test_evento_con_fase_y_picks_sigue_en_revision_prioritaria(app):
    from app.blueprints.results import _filas_revision

    job = _job()
    _reporte(job)
    destino = indicios.ruta_eventos(ruta_workspace(job.id), "seiscomp")
    destino.parent.mkdir(parents=True, exist_ok=True)
    fila = {campo: "" for campo in indicios.CAMPOS_EVENTO}
    fila.update(
        {
            "evento": "seiscomp:000001",
            "fila_catalogo": "0",
            "cruce_eventquery": "con_cruce",
            "sospechoso": "Sí",
            "fuerza": "fuerte",
            "anomalia": "Sí",
        }
    )
    with destino.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.DictWriter(
            archivo, fieldnames=indicios.CAMPOS_EVENTO
        )
        escritor.writeheader()
        escritor.writerow(fila)

    usuario = User(username="tester", role="admin")
    filas = _filas_revision(
        ruta_workspace(job.id), "seiscomp", usuario
    )
    assert len(filas) == 1
    assert filas[0]["motivo"] == "ambas"
    assert filas[0]["solo_picks"] is False
    assert filas[0]["revision_prioritaria"] == "Sí"


def test_revision_muestra_boton_y_estado_pendiente(app, client, login):
    job = _job()
    _reporte(job)
    login()
    html = client.get(
        f"/jobs/{job.id}/indicios",
        query_string={"fuente": "seiscomp", "alcance": "picks"},
    ).get_data(as_text=True)
    assert "Analizar señal" in html
    assert "señal pendiente" in html
    assert "Filtro activo: Sin aportar" in html


def test_revision_muestra_conteo_de_senal(app, client, login):
    job = _job()
    _reporte(job)
    workspace = ruta_workspace(job.id)
    picks_coverage.actualizar_senal(
        workspace,
        "seiscomp",
        "seiscomp:000001",
        senal_n=2,
        senal_estaciones="C1.A; C1.B",
        senal_estado="analizado",
    )
    login()
    html = client.get(
        f"/jobs/{job.id}/indicios",
        query_string={"fuente": "seiscomp", "alcance": "picks"},
    ).get_data(as_text=True)
    assert "2 con señal" in html
    assert "No hay eventos con señal pendiente" in html


def test_revision_muestra_sin_senal_clara(app, client, login):
    job = _job()
    _reporte(job)
    picks_coverage.actualizar_senal(
        ruta_workspace(job.id),
        "seiscomp",
        "seiscomp:000001",
        senal_n=0,
        senal_estaciones="",
        senal_estado="analizado",
    )
    login()
    html = client.get(
        f"/jobs/{job.id}/indicios",
        query_string={"fuente": "seiscomp", "alcance": "picks"},
    ).get_data(as_text=True)
    assert "sin señal clara" in html


def test_revision_muestra_sin_datos(app, client, login):
    job = _job()
    _reporte(job)
    picks_coverage.actualizar_senal(
        ruta_workspace(job.id),
        "seiscomp",
        "seiscomp:000001",
        senal_n=0,
        senal_estaciones="",
        senal_estado="sin_datos",
    )
    login()
    html = client.get(
        f"/jobs/{job.id}/indicios",
        query_string={"fuente": "seiscomp", "alcance": "picks"},
    ).get_data(as_text=True)
    assert "sin datos" in html


def test_estado_senal_devuelve_resultado(app, client, login, monkeypatch):
    job = _job()

    class Resultado:
        state = "SUCCESS"
        result = {
            "estado": "ok",
            "eventos": 2,
            "con_senal": 1,
            "sin_senal": 1,
            "sin_datos": 0,
        }

    monkeypatch.setattr(
        "app.blueprints.results.celery.AsyncResult",
        lambda task_id: Resultado(),
    )
    login()
    respuesta = client.get(f"/jobs/{job.id}/indicios/senal/tarea-1")
    assert respuesta.status_code == 200
    datos = respuesta.get_json()
    assert datos["estado"] == "ok"
    assert datos["resultado"]["con_senal"] == 1
