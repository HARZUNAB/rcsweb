"""Pruebas de la ruta de análisis de señal de estaciones sin aportar."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime

from app.extensions import db
from app.models import Job, JobSource, User, nuevo_uuid
from app.services import indicios, picks_coverage, picks_signal
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


def test_post_analizar_senal_seleccionados(app, client, login, monkeypatch):
    job = _job()
    _reporte(job)
    app.config["RCS_DISPONIBILIDAD_URL"] = "http://sidecar:8010"
    llamadas = []

    class Tarea:
        id = "tarea-senal-2"

    def encolar(*argumentos, **opciones):
        llamadas.append((argumentos, opciones))
        return Tarea()

    monkeypatch.setattr(
        "app.blueprints.results.analizar_senal_picks_task.delay", encolar
    )
    login()
    respuesta = client.post(
        f"/jobs/{job.id}/indicios/senal",
        data={
            "fuente": "seiscomp",
            "eventos": "seiscomp:000001",
        },
    )
    assert respuesta.status_code == 202
    assert respuesta.get_json()["seleccionados"] is True
    assert llamadas[0][1]["event_ids"] == ["seiscomp:000001"]


def test_crear_corrida_encola_y_guarda_items(app, client, login, monkeypatch):
    from app.models import PicksSignalRun

    job = _job()
    _reporte(job)
    app.config["RCS_DISPONIBILIDAD_URL"] = "http://sidecar:8010"
    llamadas = []
    monkeypatch.setattr(
        "app.blueprints.results.procesar_corrida_senal.delay",
        lambda run_id: llamadas.append(run_id),
    )
    login()
    respuesta = client.post(
        f"/jobs/{job.id}/indicios/senal/corrida",
        data={"fuente": "seiscomp"},
    )
    assert respuesta.status_code == 202
    datos = respuesta.get_json()
    assert datos["total"] == 1
    run = db.session.get(PicksSignalRun, datos["run_id"])
    assert run is not None
    assert run.status == "queued"
    assert [item.event_id for item in run.items] == ["seiscomp:000001"]
    assert llamadas == [run.id]


def test_estado_pausa_reanudar_y_cancelar_corrida(
    app, client, login, monkeypatch
):
    from app.models import PicksSignalRun
    from app.services import picks_signal_runs

    job = _job()
    _reporte(job)
    run = picks_signal_runs.crear_corrida(
        job.id,
        "seiscomp",
        [{"evento": "seiscomp:000001", "senal_pendiente": True}],
    )
    monkeypatch.setattr(
        "app.blueprints.results.procesar_corrida_senal.delay",
        lambda _run_id: None,
    )
    login()

    estado = client.get(
        f"/jobs/{job.id}/indicios/senal/corrida/{run.id}"
    )
    assert estado.status_code == 200
    assert estado.get_json()["estado"] == "queued"

    pausada = client.post(
        f"/jobs/{job.id}/indicios/senal/corrida/{run.id}/pausar"
    )
    assert pausada.get_json()["estado"] == "paused"

    reanudada = client.post(
        f"/jobs/{job.id}/indicios/senal/corrida/{run.id}/reanudar"
    )
    assert reanudada.get_json()["estado"] == "queued"

    cancelada = client.post(
        f"/jobs/{job.id}/indicios/senal/corrida/{run.id}/cancelar"
    )
    assert cancelada.get_json()["estado"] == "cancelled"
    assert db.session.get(PicksSignalRun, run.id).status == "cancelled"


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


def test_orden_recomendado_prioriza_por_niveles():
    from app.blueprints.results import _clave_orden_recomendado

    def fila(evento, **datos):
        base = {
            "evento": evento,
            "solo_picks": False,
            "cruce_eventquery": "con_cruce",
            "sospechoso": "Sí",
            "prioridad_base": "Alta",
            "cobertura_fuerte": 1,
            "picks_total": 10,
            "ratio_sin_aportar": 0.5,
            "picks_min_distancia": 100,
            "_fecha_orden": 1,
        }
        base.update(datos)
        return base

    nivel_a = fila("A")
    nivel_b = fila(
        "B",
        sospechoso="No",
        prioridad_base="Media",
        picks_total=60,
        ratio_sin_aportar=0.8,
        picks_min_distancia=50,
    )
    solo_picks = fila("C", solo_picks=True, picks_total=60)

    ordenadas = sorted(
        [solo_picks, nivel_b, nivel_a], key=_clave_orden_recomendado
    )
    assert [item["evento"] for item in ordenadas] == ["A", "B", "C"]

    mas_estaciones = fila("D", picks_total=60, ratio_sin_aportar=0.7)
    ordenadas = sorted(
        [nivel_a, mas_estaciones], key=_clave_orden_recomendado
    )
    assert [item["evento"] for item in ordenadas] == ["D", "A"]


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
    assert "Cola de señal" in html
    assert "Analizar estos 1" in html
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
    assert "No hay eventos pendientes de señal en este filtro." in html


def test_filtro_senal_pendiente_y_con_senal(app, client, login):
    job = _job()
    _reporte(job)
    picks_coverage.actualizar_senal(
        ruta_workspace(job.id),
        "seiscomp",
        "seiscomp:000001",
        senal_n=2,
        senal_estaciones="C1.A; C1.B",
        senal_estado="analizado",
    )
    login()
    pendientes = client.get(
        f"/jobs/{job.id}/indicios",
        query_string={
            "fuente": "seiscomp",
            "alcance": "picks",
            "senal": "pendiente",
        },
    ).get_data(as_text=True)
    assert "seiscomp:000001" not in pendientes

    con_senal = client.get(
        f"/jobs/{job.id}/indicios",
        query_string={
            "fuente": "seiscomp",
            "alcance": "picks",
            "senal": "con_senal",
        },
    ).get_data(as_text=True)
    assert "seiscomp:000001" in con_senal


def test_revision_muestra_ultimo_resumen_de_senal(app, client, login):
    job = _job()
    _reporte(job)
    picks_signal.guardar_resumen(
        ruta_workspace(job.id),
        "seiscomp",
        {
            "eventos": 50,
            "con_senal": 38,
            "sin_datos": 12,
            "actualizado": "2026-11-26T13:35:00+00:00",
        },
    )
    login()
    html = client.get(
        f"/jobs/{job.id}/indicios",
        query_string={"fuente": "seiscomp", "alcance": "picks"},
    ).get_data(as_text=True)
    assert "Último análisis" in html
    assert "38 con señal" in html
    assert "12 sin datos" in html


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
