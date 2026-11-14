"""Pruebas de las rutas de indicios y de la solicitud de revisión."""

from __future__ import annotations

import json
import zipfile

from app.domain.catalogs import canonical
from app.extensions import db
from app.models import (
    Job,
    JobSource,
    ReviewRequest,
    ReviewRequestEvent,
    User,
    nuevo_uuid,
    utcnow,
)
from app.services import indicios, review_reports
from app.services.workspace import crear_workspace


def _evento(
    analyst: str,
    *,
    event_id: str,
    source_event_id: str,
    raw_index: int = 2650,
) -> dict:
    return {
        "source_id": "seiscomp",
        "event_id": event_id,
        "source_event_id": source_event_id,
        "event_time": "2026-10-28 15:23:36",
        "latitude": -52.857,
        "longitude": -71.570,
        "depth_km": 10.0,
        "magnitude": 3.0,
        "analyst": analyst,
        "raw_index": raw_index,
        "raw": {},
    }


def _arribo(event_id: str, estacion: str, lat: float, lon: float, pick: str, residual: float) -> dict:
    return {
        "source_id": "seiscomp",
        "event_id": event_id,
        "network": "C1",
        "station": estacion,
        "phase": "P",
        "pick_time": pick,
        "residual": residual,
        "weight": 1.0,
        "is_used_in_solution": True,
        "azimuth": 180.0,
        "station_latitude": lat,
        "station_longitude": lon,
        "raw": {},
    }


def _preparar(app, admin: User):
    job = Job(
        id=nuevo_uuid(),
        status="done",
        period_start=None,
        period_end=None,
        created_by_id=admin.id,
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
            capabilities=["eventos", "arribos", "inventario"],
        )
    )
    db.session.commit()
    workspace = crear_workspace(job.id)
    eventos = [
        _evento(
            "mdur",
            event_id="seiscomp:000001",
            source_event_id="csn_sc62026vdkls",
            raw_index=0,
        ),
        _evento(
            "otro",
            event_id="seiscomp:000002",
            source_event_id="csn_otro",
            raw_index=1,
        ),
    ]
    arribos = [
        _arribo("seiscomp:000001", "MG04", -52.857232, -71.569992, "2026-10-28 15:27:41.921878", 244.2),
        _arribo("seiscomp:000001", "MG03", -51.67, -71.57, "2026-10-28 15:27:41.512964", 223.47),
        _arribo("seiscomp:000001", "MG02", -51.43, -71.57, "2026-10-28 15:27:44.457146", 222.98),
        _arribo("seiscomp:000001", "USHA", -50.15, -71.57, "2026-10-28 15:27:43.230404", 203.63),
        _arribo("seiscomp:000001", "AY05", -45.0, -71.57, "2026-10-28 15:27:42.576141", 132.89),
        _arribo("seiscomp:000002", "OTRA", 0.5, 0.0, "2026-10-28 15:23:41", 200.0),
    ]
    canonical.escribir_registros(canonical.ruta_canonica(workspace, "seiscomp"), eventos)
    canonical.escribir_registros(canonical.ruta_arribos(workspace, "seiscomp"), arribos)
    indicios.generar_indicios(workspace, ["seiscomp"], job_id=job.id)
    (workspace / "datos").mkdir(exist_ok=True)
    (workspace / "datos" / "seiscomp_parametros.csv").write_text(
        ",Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista\n"
        "0,2026-10-28 15:23:36,-52.857,-71.570,10.0,3.0,M,mdur\n"
        "1,2026-10-28 15:23:36,-52.857,-71.570,10.0,3.0,M,otro\n",
        encoding="utf-8",
    )
    (workspace / "resultados" / "indice.json").write_text(
        json.dumps(
            {
                "catalogos": {
                    "seiscomp": {
                        "archivo": "datos/seiscomp_parametros.csv",
                        "filas": 2,
                        "columnas": [
                            "",
                            "Fecha_Hora",
                            "Latitud",
                            "Longitud",
                            "Prof.",
                            "Mag.",
                            "Tipo_mag.",
                            "Analista",
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return job


def test_lista_y_detalle_de_indicios(app, client, login):
    admin = User.query.filter_by(username="tester").first()
    job = _preparar(app, admin)
    login()

    listado = client.get(f"/jobs/{job.id}/indicios?fuente=seiscomp&alcance=todos")
    assert listado.status_code == 200
    html = listado.get_data(as_text=True)
    assert "Revisión de eventos" in html
    assert "Motivo" in html
    assert "Cobertura" in html
    assert "csn_sc62026vdkls" in html
    assert "Revisión prioritaria" in html
    assert "Prioridad" in html
    assert "data-sortable" in html
    assert "tabla_orden.js" in html
    assert "Mapa</a>" not in html
    assert "/resultados/catalogos/seiscomp/0" in html
    assert "#indicios-fases" in html
    assert "Puntual" in html
    assert "Estaciones" in html
    assert "mdur" in html
    assert "Sin usuario" in html
    assert "inversion" not in html.lower()

    ajeno = client.get(
        f"/jobs/{job.id}/indicios?fuente=seiscomp&alcance=todos&analista=fuente:mdur"
    )
    assert ajeno.status_code == 200
    html_ajeno = ajeno.get_data(as_text=True)
    assert "csn_sc62026vdkls" in html_ajeno
    assert "csn_otro" not in html_ajeno
    assert 'value="fuente:mdur"' in html_ajeno

    detalle = client.get(
        f"/jobs/{job.id}/resultados/catalogos/seiscomp/0"
    )
    assert detalle.status_code == 200
    html = detalle.get_data(as_text=True)
    assert "Revisión del evento" in html
    assert "Cobertura" in html
    assert "Evidencia" in html
    assert "244.2" in html
    assert "La revisión se solicita desde el" in html
    assert "Pedir revisión" not in html
    assert "data-sortable" in html
    assert "tabla_orden.js" in html
    assert "Fase inconsistente con la distancia" in html
    assert "inversion" not in html.lower()

    antigua = client.get(
        f"/jobs/{job.id}/indicios/seiscomp/seiscomp:000001"
    )
    assert antigua.status_code == 404


def test_filas_sospechosas_sin_fase(monkeypatch, tmp_path):
    from app.blueprints import results as results_bp

    datos = {
        "eventos": [
            {
                "sospechoso": True,
                "origen": {
                    "tabla": "catalogos",
                    "opcion": "seiscomp",
                    "fila": 900,
                },
            },
            {
                "sospechoso": False,
                "origen": {
                    "tabla": "catalogos",
                    "opcion": "seiscomp",
                    "fila": 901,
                },
            },
            {
                "sospechoso": True,
                "origen": {
                    "tabla": "catalogos",
                    "opcion": "seiscomp",
                    "fila": 902,
                },
            },
        ]
    }

    def _evento(fila, event_id):
        return {
            "event_id": event_id,
            "source_event_id": f"e{fila}",
            "event_time": "2026-10-29 10:00:00",
            "latitude": -30.0,
            "longitude": -71.0,
            "depth_km": 30.0,
            "magnitude": 4.0,
            "analyst": "mdur",
            "raw_index": fila,
            "raw": {},
        }

    monkeypatch.setattr(results_bp.panels, "cargar", lambda *a, **k: datos)
    monkeypatch.setattr(
        results_bp.canonical,
        "leer_canonico",
        lambda *a, **k: [
            _evento(900, "seiscomp:000900"),
            _evento(901, "seiscomp:000901"),
            _evento(902, "seiscomp:000902"),
        ],
    )
    monkeypatch.setattr(
        results_bp.indicios, "indice_publicados", lambda *a, **k: {}
    )
    monkeypatch.setattr(
        results_bp.indicios,
        "estado_publicado",
        lambda ws, fuente, evento, indice=None: evento["raw_index"] != 902,
    )
    monkeypatch.setattr(
        results_bp.canonical,
        "leer_arribos",
        lambda *a, **k: [
            {
                "event_id": "seiscomp:000900",
                "network": "C1",
                "station": estacion,
                "phase": "P",
                "pick_time": "2026-10-29 10:00:10",
                "residual": 0.1,
                "weight": 1.0,
                "is_used_in_solution": True,
                "azimuth": azimut,
                "station_latitude": -30.0,
                "station_longitude": -71.0,
                "raw": {},
            }
            for estacion, azimut in (
                ("A01", 0.0),
                ("A02", 120.0),
                ("A03", 240.0),
            )
        ],
    )
    monkeypatch.setattr(
        results_bp.canonical,
        "leer_estaciones_sin_arribos",
        lambda *a, **k: [
            {
                "event_id": "seiscomp:000900",
                "network": "C1",
                "station": "A04",
                "raw": {},
            }
        ],
    )

    filas = results_bp._filas_sospechosas_sin_fase(
        tmp_path, "seiscomp", []
    )

    assert [fila["evento"] for fila in filas] == ["seiscomp:000900"]
    assert filas[0]["motivo"] == "sospechosa"
    assert filas[0]["patron"] == "sin_fase"
    assert filas[0]["publicado"] == "Sí"
    assert filas[0]["sospechoso"] == "Sí"
    assert filas[0]["analista"] == "mdur"
    assert filas[0]["n_usadas"] == 3
    assert filas[0]["n_disponibles"] == 4
    assert filas[0]["contexto"] == "débil"
    assert filas[0]["max_residual_usado"] == "0.10"


def test_solicitar_revision_encola_informe(app, client, login, monkeypatch):
    admin = User.query.filter_by(username="tester").first()
    job = _preparar(app, admin)
    analista = User(username="mdur", role="analista", analyst_code="mdur")
    analista.set_password("secret")
    db.session.add(analista)
    db.session.commit()
    login()

    estados = {}
    monkeypatch.setattr(
        review_reports, "guardar_estado", lambda key, datos: estados.__setitem__(key, dict(datos))
    )
    monkeypatch.setattr(
        review_reports, "leer_estado", lambda key: estados.get(key)
    )
    encolados = []
    monkeypatch.setattr(
        "tasks.reports.generar_informe_revision.delay",
        lambda report_id: encolados.append(report_id),
    )

    respuesta = client.post(
        f"/jobs/{job.id}/indicios/revision",
        data={
            "fuente": "seiscomp",
            "eventos": ["0"],
            "formato": "pdf",
            "nota": "Revisar la asociación de las P.",
        },
    )
    assert respuesta.status_code == 200
    report_id = respuesta.get_json()["report_id"]
    assert encolados == [report_id]
    estado = estados[report_id]
    assert estado["job_id"] == job.id
    assert estado["assigned_to_id"] == analista.id
    assert estado["nota"] == "Revisar la asociación de las P."
    assert len(estado["filas"]) == 1
    assert estado["filas"][0]["evento"] == "seiscomp:000001"


def test_solicitar_revision_exige_un_solo_analista(app, client, login):
    admin = User.query.filter_by(username="tester").first()
    job = _preparar(app, admin)
    login()

    respuesta = client.post(
        f"/jobs/{job.id}/indicios/revision",
        data={"fuente": "seiscomp", "eventos": ["0", "1"]},
    )
    assert respuesta.status_code == 400
    assert "un solo analista" in respuesta.get_json()["error"]


def test_solicitar_revision_rechaza_conflicto_y_permite_cerrada(
    app, client, login, monkeypatch
):
    admin = User.query.filter_by(username="tester").first()
    job = _preparar(app, admin)
    analista = User(username="mdur", role="analista", analyst_code="mdur")
    analista.set_password("secret")
    db.session.add(analista)
    db.session.flush()
    solicitud = ReviewRequest(
        job_id=job.id,
        source_id="seiscomp",
        created_by_id=admin.id,
        assigned_to_id=analista.id,
        status="notificada",
        notified_at=utcnow(),
        report_format="pdf",
    )
    db.session.add(solicitud)
    db.session.flush()
    db.session.add(
        ReviewRequestEvent(
            request_id=solicitud.id,
            source_id="seiscomp",
            event_id="seiscomp:000001",
            source_event_id="csn_sc62026vdkls",
            fila_catalogo=0,
        )
    )
    db.session.commit()
    login()

    estados = {}
    monkeypatch.setattr(
        review_reports,
        "guardar_estado",
        lambda key, datos: estados.__setitem__(key, dict(datos)),
    )
    monkeypatch.setattr(
        review_reports, "leer_estado", lambda key: estados.get(key)
    )
    monkeypatch.setattr(
        "tasks.reports.generar_informe_revision.delay", lambda report_id: None
    )

    respuesta = client.post(
        f"/jobs/{job.id}/indicios/revision",
        data={"fuente": "seiscomp", "eventos": ["0"]},
    )
    assert respuesta.status_code == 409
    assert "ya están en revisión" in respuesta.get_json()["error"]

    solicitud.status = "cerrada"
    db.session.commit()
    respuesta = client.post(
        f"/jobs/{job.id}/indicios/revision",
        data={"fuente": "seiscomp", "eventos": ["0"]},
    )
    assert respuesta.status_code == 200
    assert respuesta.get_json()["report_id"]


def test_ejecutar_informe_genera_docx(app, client, login, monkeypatch):
    admin = User.query.filter_by(username="tester").first()
    job = _preparar(app, admin)
    analista = User(username="mdur", role="analista", analyst_code="mdur")
    analista.set_password("secret")
    db.session.add(analista)
    db.session.commit()
    login()

    estados = {}
    monkeypatch.setattr(
        review_reports,
        "guardar_estado",
        lambda key, datos: estados.__setitem__(key, dict(datos)),
    )
    monkeypatch.setattr(
        review_reports, "leer_estado", lambda key: estados.get(key)
    )
    monkeypatch.setattr(
        "tasks.reports.generar_informe_revision.delay", lambda report_id: None
    )

    respuesta = client.post(
        f"/jobs/{job.id}/indicios/revision",
        data={"fuente": "seiscomp", "eventos": ["0"], "formato": "docx"},
    )
    assert respuesta.status_code == 200
    report_id = respuesta.get_json()["report_id"]

    resultado = review_reports.ejecutar(report_id)
    assert resultado["estado"] == "listo"

    solicitud = ReviewRequest.query.filter_by(job_id=job.id).one()
    assert solicitud.report_format == "docx"
    assert solicitud.report_path.endswith(".docx")
    ruta = crear_workspace(job.id) / solicitud.report_path
    assert zipfile.is_zipfile(ruta)


def test_revisiones_visibilidad_y_ciclo(app, client, login):
    admin = User.query.filter_by(username="tester").first()
    job = _preparar(app, admin)
    analista = User(username="mdur", role="analista", analyst_code="mdur")
    analista.set_password("secret")
    otro = User(username="otro", role="analista", analyst_code="otro")
    otro.set_password("secret")
    db.session.add_all([analista, otro])
    db.session.flush()
    solicitud = ReviewRequest(
        job_id=job.id,
        source_id="seiscomp",
        created_by_id=admin.id,
        assigned_to_id=analista.id,
        status="notificada",
        notified_at=utcnow(),
        report_format="pdf",
    )
    db.session.add(solicitud)
    db.session.commit()
    login()

    listado = client.get("/revisiones")
    assert listado.status_code == 200
    assert job.id[:8] in listado.get_data(as_text=True)
    assert client.post(f"/revisiones/{solicitud.id}/aceptar").status_code == 403

    client.post("/logout")
    client.post(
        "/login",
        data={"username": "mdur", "password": "secret"},
    )
    listado = client.get("/revisiones")
    assert job.id[:8] in listado.get_data(as_text=True)
    detalle = client.get(f"/revisiones/{solicitud.id}")
    assert detalle.status_code == 200
    assert "Aceptar solicitud" in detalle.get_data(as_text=True)

    respuesta = client.post(f"/revisiones/{solicitud.id}/aceptar")
    assert respuesta.status_code == 302
    db.session.refresh(solicitud)
    assert solicitud.status == "en_proceso"
    assert solicitud.accepted_at is not None

    respuesta = client.post(
        f"/revisiones/{solicitud.id}/cerrar", data={"antecedentes": ""}
    )
    assert respuesta.status_code == 302
    db.session.refresh(solicitud)
    assert solicitud.status == "en_proceso"
    assert solicitud.closing_note is None

    respuesta = client.post(
        f"/revisiones/{solicitud.id}/cerrar",
        data={"antecedentes": "Se revisaron las fases y se confirmó el pick."},
    )
    assert respuesta.status_code == 302
    db.session.refresh(solicitud)
    assert solicitud.status == "cerrada"
    assert solicitud.closed_at is not None
    assert "confirmó el pick" in solicitud.closing_note

    client.post("/logout")
    client.post(
        "/login",
        data={"username": "otro", "password": "secret"},
    )
    listado = client.get("/revisiones")
    assert job.id[:8] not in listado.get_data(as_text=True)
    assert client.get(f"/revisiones/{solicitud.id}").status_code == 403


def test_ejecutar_informe_crea_solicitud_con_pdf(
    app, client, login, monkeypatch
):
    admin = User.query.filter_by(username="tester").first()
    job = _preparar(app, admin)
    analista = User(username="mdur", role="analista", analyst_code="mdur")
    analista.set_password("secret")
    db.session.add(analista)
    db.session.commit()
    login()

    estados = {}
    monkeypatch.setattr(
        review_reports, "guardar_estado", lambda key, datos: estados.__setitem__(key, dict(datos))
    )
    monkeypatch.setattr(
        review_reports, "leer_estado", lambda key: estados.get(key)
    )
    monkeypatch.setattr(
        "tasks.reports.generar_informe_revision.delay", lambda report_id: None
    )

    respuesta = client.post(
        f"/jobs/{job.id}/indicios/revision",
        data={"fuente": "seiscomp", "eventos": ["0"], "formato": "pdf"},
    )
    assert respuesta.status_code == 200
    report_id = respuesta.get_json()["report_id"]

    resultado = review_reports.ejecutar(report_id)
    assert resultado["estado"] == "listo"

    solicitud = ReviewRequest.query.filter_by(job_id=job.id).one()
    assert solicitud.status == "notificada"
    assert solicitud.assigned_to_id == analista.id
    assert solicitud.created_by_id == admin.id
    assert solicitud.report_format == "pdf"
    assert [evento.event_id for evento in solicitud.events] == [
        "seiscomp:000001"
    ]
    assert solicitud.events[0].fila_catalogo == 0
    assert solicitud.events[0].analyst == "mdur"
    ruta = crear_workspace(job.id) / solicitud.report_path
    assert ruta.is_file()
    assert ruta.read_bytes().startswith(b"%PDF")

    detalle = client.get(f"/revisiones/{solicitud.id}")
    assert detalle.status_code == 200
    assert "Solicitud #" in detalle.get_data(as_text=True)


def test_analista_ve_solo_sus_eventos_y_no_puede_pedir_revision(app, client):
    admin = User.query.filter_by(username="tester").first()
    job = _preparar(app, admin)

    analista = User(username="analista", role="analista", analyst_code="mdur")
    analista.set_password("secret")
    db.session.add(analista)
    db.session.flush()
    job.created_by_id = analista.id
    db.session.commit()

    client.post("/login", data={"username": "analista", "password": "secret"})

    listado = client.get(f"/jobs/{job.id}/indicios?fuente=seiscomp&alcance=todos")
    assert listado.status_code == 200
    html = listado.get_data(as_text=True)
    assert "csn_sc62026vdkls" in html
    assert "csn_otro" not in html
    assert "Pedir revisión" not in html

    propio = client.get(
        f"/jobs/{job.id}/resultados/catalogos/seiscomp/0"
    )
    assert propio.status_code == 200
    ajeno = client.get(
        f"/jobs/{job.id}/resultados/catalogos/seiscomp/1"
    )
    assert ajeno.status_code == 403

    respuesta = client.post(
        f"/jobs/{job.id}/indicios/revision",
        data={"fuente": "seiscomp", "evento": "seiscomp:000001"},
    )
    assert respuesta.status_code == 403


def test_listado_y_detalle_reutilizan_la_clasificacion_sospechoso(
    app, client, login, monkeypatch
):
    admin = User.query.filter_by(username="tester").first()
    job = _preparar(app, admin)
    workspace = crear_workspace(job.id)
    (workspace / "datos").mkdir(exist_ok=True)
    (workspace / "resultados").mkdir(exist_ok=True)
    (workspace / "datos" / "seiscomp_parametros.csv").write_text(
        ",Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista\n"
        "0,2026-10-28 15:23:36,-52.857,-71.570,10.0,3.0,M,mdur\n"
        "1,2026-10-28 15:23:36,-52.857,-71.570,10.0,3.0,M,otro\n",
        encoding="utf-8",
    )
    (workspace / "resultados" / "indice.json").write_text(
        json.dumps(
            {
                "catalogos": {
                    "seiscomp": {
                        "archivo": "datos/seiscomp_parametros.csv",
                        "filas": 2,
                        "columnas": [
                            "",
                            "Fecha_Hora",
                            "Latitud",
                            "Longitud",
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    def _clasificar(*_args, **_kwargs):
        return (
            [
                {
                    "latitud": -52.857,
                    "longitud": -71.570,
                    "sospechoso": True,
                    "residuo_km": 39.4,
                    "perp_km": 34.6,
                    "along_km": 250.0,
                }
            ],
            {"id": "perfil-prueba"},
        )

    monkeypatch.setattr(
        "app.blueprints.results.clasificar_eventos", _clasificar
    )
    login()

    listado = client.get(
        f"/jobs/{job.id}/indicios?fuente=seiscomp&alcance=todos"
    )
    html = listado.get_data(as_text=True)
    assert "Sospechosa" in html
    assert "residuo 39.4 km" in html

    detalle = client.get(
        f"/jobs/{job.id}/resultados/catalogos/seiscomp/0"
    )
    html = detalle.get_data(as_text=True)
    assert "sospechosa" in html
    assert "residuo al slab 39.4 km" in html
    assert "Ver planta y perfil" not in html
    assert "Ver tiempos de llegada" not in html
    assert "Ver evidencia del indicio" in html
    assert "Evidencia principal:" in html
    assert 'id="planta-perfil"' in html
    assert "modal-tiempos" in html
    assert "tiempos-llegada-datos" in html
    assert "Peso (0-4)" in html
    assert "Original:" in html

    listado = client.get(
        f"/jobs/{job.id}/indicios?fuente=seiscomp&alcance=todos"
    )
    html = listado.get_data(as_text=True)
    assert "Mapa</a>" not in html
    assert "#indicios-fases" in html
