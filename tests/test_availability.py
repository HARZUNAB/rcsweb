"""Pruebas del servicio auxiliar y del cliente de disponibilidad."""

from __future__ import annotations

import threading
from datetime import UTC, datetime

import requests

from app.models import Job, nuevo_uuid
from app.services import amplification, availability, availability_service
from app.services.workspace import crear_workspace
from tasks import amplification as tarea_amplification
from tasks import availability as tarea_availability


def _resultado(**extra):
    datos = {
        "status": "CON_DATOS",
        "source": "SDS",
        "desde": "2026-10-22T00:00:00",
        "hasta": "2026-10-22T00:20:00",
        "records": 10,
    }
    datos.update(extra)
    return datos


def test_servicio_valida_y_calcula_ventana(monkeypatch):
    capturado = {}

    def falso(streams, desde, hasta, al_progreso=None):
        capturado.update({"streams": streams, "desde": desde, "hasta": hasta})
        if al_progreso:
            al_progreso("Consultando el archivo SDS…")
        return {"AI.DSPA.02.BHZ": _resultado()}

    datos = availability_service.consultar(
        {
            "event_time": "2026-10-22T00:00:00",
            "streams": ["AI.DSPA.02.BHZ", "AI.DSPA.02.BHZ"],
        },
        consultar_fn=falso,
    )

    assert capturado["streams"] == ["AI.DSPA.02.BHZ"]
    assert capturado["desde"].isoformat() == "2026-10-21T23:50:00"
    assert capturado["hasta"].isoformat() == "2026-10-22T00:10:00"
    assert datos["results"]["AI.DSPA.02.BHZ"]["status"] == "CON_DATOS"
    assert datos["fuentes"] == ["SDS"]
    assert "Consultando el archivo SDS…" in datos["fases"]


def test_servicio_trocea_streams():
    lotes = []

    def falso(streams, desde, hasta, al_progreso=None):
        lotes.append(list(streams))
        return {stream: _resultado() for stream in streams}

    streams = [f"XX.EST{i:04d}.00.HHZ" for i in range(650)]
    datos = availability_service.consultar(
        {"event_time": "2026-10-22T00:00:00", "streams": streams},
        consultar_fn=falso,
    )

    assert [len(lote) for lote in lotes] == [300, 300, 50]
    assert len(datos["results"]) == 650


def test_servicio_acepta_hora_con_espacios():
    capturado = {}

    def falso(streams, desde, hasta, al_progreso=None):
        capturado.update({"desde": desde, "hasta": hasta})
        return {}

    availability_service.consultar(
        {
            "event_time": "2026-10-22  00:00:00",
            "streams": ["AI.DSPA.02.BHZ"],
        },
        consultar_fn=falso,
    )

    assert capturado["desde"].isoformat() == "2026-10-21T23:50:00"
    assert capturado["hasta"].isoformat() == "2026-10-22T00:10:00"


def test_servicio_rechaza_solicitudes_invalidas():
    for payload in (
        {},
        {"event_time": "no-es-fecha", "streams": ["A.B.C.D"]},
        {"event_time": "2026-10-22T00:00:00", "streams": []},
        {"event_time": "2026-10-22T00:00:00", "streams": "A.B.C.D"},
    ):
        try:
            availability_service.consultar(payload, consultar_fn=lambda *a, **k: {})
        except availability_service.ErrorConsulta:
            continue
        raise AssertionError(f"Se aceptó una solicitud inválida: {payload}")


def test_servicio_http_requiere_token_y_responde(monkeypatch, tmp_path):
    monkeypatch.setenv("RCS_DISPONIBILIDAD_TOKEN", "secreto")
    monkeypatch.setattr(
        availability_service.disponibilidad,
        "consultar",
        lambda streams, desde, hasta, al_progreso=None: {
            "AI.DSPA.02.BHZ": _resultado()
        },
    )
    monkeypatch.setattr(
        availability_service.disponibilidad, "ruta_scart", lambda: "/bin/true"
    )
    monkeypatch.setattr(
        availability_service.disponibilidad, "raiz_sds", lambda: str(tmp_path)
    )
    monkeypatch.setattr(
        availability_service.disponibilidad,
        "recordstream",
        lambda: "combined://slink/host:18000",
    )

    servidor = availability_service.crear_servidor("127.0.0.1", 0)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    puerto = servidor.server_address[1]
    try:
        base = f"http://127.0.0.1:{puerto}"
        sin_token = requests.post(
            f"{base}/consultar",
            json={"event_time": "2026-10-22T00:00:00", "streams": ["A.B.C.D"]},
            timeout=5,
        )
        assert sin_token.status_code == 403

        con_token = requests.post(
            f"{base}/consultar",
            headers={"X-RCS-Token": "secreto"},
            json={
                "event_time": "2026-10-22T00:00:00",
                "streams": ["AI.DSPA.02.BHZ"],
            },
            timeout=5,
        )
        assert con_token.status_code == 200
        assert con_token.json()["results"]["AI.DSPA.02.BHZ"]["source"] == "SDS"

        salud = requests.get(f"{base}/health", timeout=5)
        assert salud.status_code == 200
        assert salud.json()["ok"] is True
    finally:
        servidor.shutdown()
        servidor.server_close()
        hilo.join(timeout=5)


def test_cliente_consulta_y_errores(app, monkeypatch):
    app.config["RCS_DISPONIBILIDAD_URL"] = "http://sidecar:8010"
    app.config["RCS_DISPONIBILIDAD_TOKEN"] = "token"
    app.config["RCS_DISPONIBILIDAD_TIMEOUT"] = 10
    llamadas = {}

    class Respuesta:
        status_code = 200

        def json(self):
            return {"results": {"A.B.C.D": _resultado()}}

    def post(url, json, headers, timeout):
        llamadas.update(
            {"url": url, "json": json, "headers": headers, "timeout": timeout}
        )
        return Respuesta()

    monkeypatch.setattr(availability.requests, "post", post)
    with app.app_context():
        assert availability.configurada()
        resultados = availability.consultar("2026-10-22T00:00:00", ["A.B.C.D"])

    assert llamadas["url"] == "http://sidecar:8010/consultar"
    assert llamadas["headers"]["X-RCS-Token"] == "token"
    assert llamadas["timeout"] == 10
    assert resultados["A.B.C.D"]["status"] == "CON_DATOS"

    class ErrorRespuesta(Respuesta):
        status_code = 429

        def json(self):
            return {"error": "Hay otra consulta en curso."}

    monkeypatch.setattr(availability.requests, "post", lambda *a, **k: ErrorRespuesta())
    with app.app_context():
        try:
            availability.consultar("2026-10-22T00:00:00", ["A.B.C.D"])
        except availability.AvailabilityError as exc:
            assert "otra consulta" in str(exc)
        else:
            raise AssertionError("Se esperaba un error de disponibilidad")


def test_cliente_sin_configuracion(app):
    with app.app_context():
        app.config["RCS_DISPONIBILIDAD_URL"] = ""
        assert not availability.configurada()
        try:
            availability.consultar("2026-10-22T00:00:00", ["A.B.C.D"])
        except availability.AvailabilityError as exc:
            assert "no está configurada" in str(exc)
        else:
            raise AssertionError("Se esperaba un error de configuración")


def test_aplicar_resultados_a_filas():
    filas = [
        {
            "red": "AI",
            "estacion": "DSPA",
            "actividad_ventana": "0",
            "_streams": ["AI.DSPA.00.BHZ", "AI.DSPA.02.BHZ"],
        },
        {
            "red": "AI",
            "estacion": "OTRA",
            "actividad_ventana": "0",
            "_streams": ["AI.OTRA.00.BHZ"],
        },
        {
            "red": "AI",
            "estacion": "INDICIO",
            "actividad_ventana": "3",
            "_streams": ["AI.INDICIO.00.BHZ"],
        },
    ]
    resultados = {
        "AI.DSPA.00.BHZ": {"status": "SIN_DATOS", "source": ""},
        "AI.DSPA.02.BHZ": _resultado(),
        "AI.OTRA.00.BHZ": {"status": "SIN_DATOS", "source": ""},
        "AI.INDICIO.00.BHZ": {"status": "SIN_DATOS", "source": ""},
    }

    resumen = availability.aplicar_a_filas(filas, resultados)

    assert filas[0]["formas_onda"] == "SDS"
    assert filas[0]["evidencia"] == "Verificado (SDS)"
    assert filas[0]["disponible"] == "Sí"
    assert filas[0]["disponible_no_usada"] is True
    assert filas[1]["formas_onda"] == "Sin datos"
    assert filas[1]["evidencia"] == "Sin evidencia"
    assert filas[1]["disponible"] == "No"
    assert filas[2]["evidencia"] == "Indicio (actividad)"
    assert resumen == {
        "estaciones": 3,
        "con_datos": 1,
        "sin_datos": 2,
        "no_consultado": 0,
    }


def test_cache_conserva_otros_eventos(tmp_path):
    workspace = tmp_path / "ws"
    filas_a = [
        {
            "red": "AI",
            "estacion": "DSPA",
            "actividad_ventana": "0",
            "_streams": ["AI.DSPA.02.BHZ"],
            "formas_onda": "SDS",
            "evidencia": "Verificado (SDS)",
            "_estado_disponibilidad": "CON_DATOS",
            "_fuente_disponibilidad": "SDS",
            "cobertura_desde": "2026-10-22T00:00:00",
            "cobertura_hasta": "2026-10-22T00:20:00",
        }
    ]
    filas_b = [
        {
            "red": "AI",
            "estacion": "OTRA",
            "actividad_ventana": "0",
            "_streams": ["AI.OTRA.00.BHZ"],
            "formas_onda": "Sin datos",
            "evidencia": "Sin evidencia",
            "_estado_disponibilidad": "SIN_DATOS",
            "_fuente_disponibilidad": "",
            "cobertura_desde": "",
            "cobertura_hasta": "",
        }
    ]

    availability.guardar_cache(workspace, "seiscomp", "evento-a", filas_a)
    availability.guardar_cache(workspace, "seiscomp", "evento-b", filas_b)

    cache_a = availability.leer_cache(workspace, "seiscomp", "evento-a")
    cache_b = availability.leer_cache(workspace, "seiscomp", "evento-b")
    assert cache_a[("AI", "DSPA")]["status"] == "CON_DATOS"
    assert cache_b[("AI", "OTRA")]["status"] == "SIN_DATOS"

    # Volver a guardar el evento A no borra el B.
    availability.guardar_cache(workspace, "seiscomp", "evento-a", filas_a)
    assert availability.leer_cache(workspace, "seiscomp", "evento-b")


def test_estado_de_tarea_en_redis(app, monkeypatch):
    class FakeRedis:
        def __init__(self):
            self.datos = {}

        def get(self, clave):
            return self.datos.get(clave)

        def set(self, clave, valor, nx=False, ex=None):
            if nx and clave in self.datos:
                return False
            self.datos[clave] = valor
            return True

        def delete(self, clave):
            return 1 if self.datos.pop(clave, None) is not None else 0

    falso = FakeRedis()
    monkeypatch.setattr("app.services.availability._redis", lambda: falso)
    with app.app_context():
        assert availability.tarea_en_curso("job-1", "ev-1") == ""
        task_id, creada = availability.registrar_tarea(
            "job-1", "ev-1", "task-1"
        )
        assert (task_id, creada) == ("task-1", True)
        assert availability.tarea_en_curso("job-1", "ev-1") == "task-1"

        task_id, creada = availability.registrar_tarea(
            "job-1", "ev-1", "task-2"
        )
        assert (task_id, creada) == ("task-1", False)

        availability.limpiar_tarea("job-1", "ev-1")
        assert availability.tarea_en_curso("job-1", "ev-1") == ""


def test_ampliacion_guarda_archivo(app, monkeypatch):
    from app.extensions import db

    job = Job(
        id=nuevo_uuid(),
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 31, 23, 59, 59, tzinfo=UTC),
        status="done",
    )
    db.session.add(job)
    db.session.commit()
    workspace = crear_workspace(job.id)
    fila_base = {
        "id_evento": "csn_test_0001",
        "id_origen": "Origin/20261003155356.000",
        "red": "IU",
        "estacion": "LVC",
        "loc_ref": "00",
        "cha_ref": "BHZ",
        "streams_vigentes": 2,
        "streams_vigentes_ids": "IU.LVC.00.BHZ;IU.LVC.00.HHZ",
        "distancia_km": 123.4,
        "est_lat": -29.1,
        "est_lon": -71.1,
        "est_elev": 1200,
        "est_lugar": "Coquimbo",
        "est_pais": "Chile",
        "radio_km": None,
        "actividad_ventana": 2,
        "evidencia": "INDICIO",
        "waveform_status": "NO_CONSULTADO",
        "availability_source": "",
        "cobertura_desde": "",
        "cobertura_hasta": "",
    }
    monkeypatch.setattr(
        amplification,
        "ampliar_desde_base",
        lambda **kwargs: ([fila_base], 0),
    )
    limpiadas = []
    monkeypatch.setattr(
        amplification,
        "limpiar_tarea",
        lambda job_id, event_id, clave: limpiadas.append(
            (job_id, event_id, clave)
        ),
    )
    with app.app_context():
        resultado = tarea_amplification.ejecutar(
            job.id,
            "seiscomp",
            "seiscomp:000000",
            "seiscomp",
            "Origin/20261003155356.000",
            "2026-10-03  15:53:56",
            -29.519,
            -72.594,
            [["IU", "ANMO"]],
            None,
        )

    assert resultado["estado"] == "ok"
    assert resultado["clave"] == "sinlimite"
    assert resultado["filas"] == 1
    registros = amplification.leer_ampliacion(
        workspace, "seiscomp", "seiscomp:000000", "sinlimite"
    )
    assert registros[0]["station"] == "LVC"
    assert registros[0]["stream_ids"] == "IU.LVC.00.BHZ;IU.LVC.00.HHZ"
    assert limpiadas == [(job.id, "seiscomp:000000", "sinlimite")]


def test_tarea_guarda_cache(app, monkeypatch):
    from app.extensions import db

    job = Job(
        id=nuevo_uuid(),
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 31, 23, 59, 59, tzinfo=UTC),
        status="done",
    )
    db.session.add(job)
    db.session.commit()
    workspace = crear_workspace(job.id)
    filas = [
        {
            "red": "AI",
            "estacion": "DSPA",
            "actividad_ventana": "0",
            "_streams": ["AI.DSPA.02.BHZ"],
        }
    ]
    monkeypatch.setattr(
        "app.services.availability.consultar",
        lambda event_time, streams: {"AI.DSPA.02.BHZ": _resultado()},
    )
    limpiadas = []
    monkeypatch.setattr(
        "app.services.availability.limpiar_tarea",
        lambda job_id, event_id, vista="": limpiadas.append(
            (job_id, event_id)
        ),
    )
    with app.app_context():
        resultado = tarea_availability.ejecutar(
            job.id,
            "seiscomp",
            "seiscomp:000000",
            "2026-10-22T00:00:00",
            filas,
        )

    assert resultado["estado"] == "ok"
    assert resultado["con_datos"] == 1
    assert limpiadas == [(job.id, "seiscomp:000000")]
    cache = availability.leer_cache(
        workspace, "seiscomp", "seiscomp:000000"
    )
    assert cache[("AI", "DSPA")]["source"] == "SDS"
