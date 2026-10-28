"""Pruebas de solicitudes SSH y creación del trabajo."""

from __future__ import annotations

import re
import shutil
from datetime import UTC, datetime
from types import SimpleNamespace

from app.extensions import db
from app.models import (
    AuditLog,
    CatalogRequest,
    CatalogRequestFile,
    Job,
    User,
    nuevo_uuid,
)
from app.services.acquisition import ejecutar_solicitud, preparar_workspace

SAMPLES = __import__("pathlib").Path(__file__).resolve().parent.parent / "samples"
INICIO = "20261001000000"
FIN = "20261031235959"


def _input(html: str, nombre: str) -> str:
    return re.search(f'<input[^>]*name="{nombre}"[^>]*>', html).group(0)


def _radios(html: str) -> list[str]:
    return re.findall(r'<input[^>]*name="primary_source"[^>]*>', html)


def _solicitud(app, status="queued", fuentes=("eventquery", "seisan"), principal=None):
    solicitud = CatalogRequest(
        id=nuevo_uuid(),
        mode="ssh",
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 31, 23, 59, 59, tzinfo=UTC),
        status=status,
        primary_source=principal,
        server="10.54.217.9",
        remote_user="sysopr",
        requested_by_id=db.session.execute(
            db.select(User.id).filter_by(username="tester")
        ).scalar_one(),
    )
    db.session.add(solicitud)
    db.session.commit()
    db.session.add_all(
        [
            CatalogRequestFile(
                request_id=solicitud.id,
                kind=kind,
                format=kind,
                status="pending",
            )
            for kind in fuentes
        ]
    )
    db.session.commit()
    preparar_workspace(solicitud.id)
    return solicitud


def _traer_catalogos_falso(eventquery_valido=True):
    class Conexion:
        def __init__(self, password, log=None):
            self.password = password
            self.log = log

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def verificar_conexion(conexion, log=None, progreso=None):
        if progreso:
            progreso(1.0)

    def traer_seisan(inicio, fin, conexion, cwd=".", log=None, progreso=None, forzar=False):
        assert forzar is True
        destino = __import__("pathlib").Path(cwd) / f"select_{inicio}_{fin}.out"
        shutil.copy2(SAMPLES / "select.out", destino)
        if progreso:
            progreso(1.0)
        return str(destino)

    def traer_eventquery(inicio, fin, conexion, cwd=".", log=None, progreso=None, forzar=False):
        assert forzar is True
        destino = __import__("pathlib").Path(cwd) / f"eventquery_{inicio}_{fin}.csv"
        if eventquery_valido:
            shutil.copy2(
                SAMPLES / "eventquery_20261001000000_20261031235959.csv",
                destino,
            )
        else:
            destino.write_text("a,b\n1,2\n", encoding="utf-8")
        if progreso:
            progreso(1.0)
        return str(destino)

    return SimpleNamespace(
        IP_REMOTA="10.54.217.9",
        USUARIO_REMOTO="sysopr",
        Conexion=Conexion,
        verificar_conexion=verificar_conexion,
        traer_seisan=traer_seisan,
        traer_eventquery=traer_eventquery,
    )


def test_nueva_solicitud_encola(client, login, monkeypatch):
    login()
    llamadas = []
    monkeypatch.setattr(
        "app.blueprints.solicitudes.encolar_solicitud",
        lambda request_id, password: llamadas.append((request_id, password)),
    )

    respuesta = client.post(
        "/solicitudes/nueva",
        data={
            "period_start": "2026-10-01",
            "period_end": "2026-10-31",
            "server": "10.54.217.9",
            "remote_user": "sysopr",
            "password": "secreto",
            "incluir_seisan": "y",
            "primary_source": "seisan",
        },
    )

    assert respuesta.status_code == 302
    solicitud = db.session.execute(db.select(CatalogRequest)).scalar_one()
    assert solicitud.status == "queued"
    assert solicitud.server == "10.54.217.9"
    assert solicitud.remote_user == "sysopr"
    assert solicitud.primary_source == "seisan"
    assert {archivo.kind for archivo in solicitud.files} == {"eventquery", "seisan"}
    assert llamadas == [(solicitud.id, "secreto")]
    assert (
        db.session.execute(db.select(AuditLog).filter_by(action="catalog.request"))
        .scalar_one()
        .entity
        == solicitud.id
    )


def test_nueva_por_defecto_sin_seiscomp(client, login, monkeypatch):
    login()
    monkeypatch.setattr("app.blueprints.solicitudes.seiscomp_configurada", lambda: False)

    html = client.get("/solicitudes/nueva").get_data(as_text=True)

    assert "checked" in _input(html, "incluir_seisan")
    assert "checked" not in _input(html, "incluir_seiscomp")
    marcado = [radio for radio in _radios(html) if "checked" in radio]
    assert len(marcado) == 1
    assert 'value="seisan"' in marcado[0]


def test_nueva_por_defecto_elige_seiscomp_si_esta_configurado(client, login, monkeypatch):
    login()
    monkeypatch.setattr("app.blueprints.solicitudes.seiscomp_configurada", lambda: True)

    html = client.get("/solicitudes/nueva").get_data(as_text=True)

    assert "checked" in _input(html, "incluir_seiscomp")
    assert "checked" not in _input(html, "incluir_seisan")
    marcado = [radio for radio in _radios(html) if "checked" in radio]
    assert len(marcado) == 1
    assert 'value="seiscomp"' in marcado[0]


def test_nueva_solicitud_exige_fuente_local(client, login):
    login()

    respuesta = client.post(
        "/solicitudes/nueva",
        data={
            "period_start": "2026-10-01",
            "period_end": "2026-10-31",
            "server": "10.54.217.9",
            "remote_user": "sysopr",
            "password": "secreto",
        },
    )

    assert respuesta.status_code == 200
    assert "Seleccioná al menos una fuente local" in respuesta.get_data(as_text=True)
    assert db.session.execute(db.select(CatalogRequest)).scalar_one_or_none() is None


def test_nueva_solicitud_con_seiscomp(client, login, monkeypatch):
    login()
    monkeypatch.setattr("app.services.seiscomp.configurada", lambda: True)
    llamadas = []
    monkeypatch.setattr(
        "app.blueprints.solicitudes.encolar_solicitud",
        lambda request_id, password: llamadas.append((request_id, password)),
    )

    respuesta = client.post(
        "/solicitudes/nueva",
        data={
            "period_start": "2026-10-01",
            "period_end": "2026-10-31",
            "server": "10.54.217.9",
            "remote_user": "sysopr",
            "password": "secreto",
            "incluir_seiscomp": "y",
            "primary_source": "seiscomp",
        },
    )

    assert respuesta.status_code == 302
    solicitud = db.session.execute(db.select(CatalogRequest)).scalar_one()
    assert solicitud.primary_source == "seiscomp"
    assert {archivo.kind for archivo in solicitud.files} == {"eventquery", "seiscomp"}
    assert llamadas == [(solicitud.id, "secreto")]


def test_probar_seiscomp_sin_configuracion(client, login, monkeypatch):
    login()
    monkeypatch.setattr(
        "app.blueprints.solicitudes.probar_conexion",
        lambda: {
            "ok": False,
            "error": "Faltan SEISCOMP_DB_HOST/USER/PASSWORD.",
            "bases": [],
        },
    )

    respuesta = client.post("/solicitudes/probar-seiscomp", follow_redirects=True)

    assert respuesta.status_code == 200
    assert "Faltan SEISCOMP_DB_HOST/USER/PASSWORD" in respuesta.get_data(as_text=True)


def test_lista_y_detalle(client, login, app):
    login()
    solicitud = _solicitud(app)

    assert client.get("/solicitudes/").status_code == 200
    respuesta = client.get(f"/solicitudes/{solicitud.id}")
    assert respuesta.status_code == 200
    assert "10.54.217.9" in respuesta.get_data(as_text=True)


def test_ejecutar_solicitud_crea_job(app, monkeypatch):
    solicitud = _solicitud(app)
    encolados = []
    monkeypatch.setattr(
        "app.services.acquisition._cargar_traer_catalogos",
        lambda: _traer_catalogos_falso(True),
    )
    monkeypatch.setattr(
        "app.services.acquisition.encolar_trabajo",
        lambda job_id: encolados.append(job_id),
    )

    resultado = ejecutar_solicitud(solicitud.id, "secreto")

    assert resultado["estado"] == "done"
    db.session.expire_all()
    solicitud = db.session.get(CatalogRequest, solicitud.id)
    assert solicitud.status == "done"
    assert solicitud.progress == 100
    job = db.session.execute(db.select(Job)).scalar_one()
    assert job.origin == "ssh"
    assert job.catalog_request_id == solicitud.id
    assert {source.kind for source in job.sources} == {"eventquery", "seisan"}
    assert {archivo.kind for archivo in job.files} == {"eventquery", "seisan"}
    assert encolados == [job.id]


def test_ejecutar_solicitud_invalida_no_crea_job(app, monkeypatch):
    solicitud = _solicitud(app)
    monkeypatch.setattr(
        "app.services.acquisition._cargar_traer_catalogos",
        lambda: _traer_catalogos_falso(False),
    )
    monkeypatch.setattr("app.services.acquisition.encolar_trabajo", lambda _id: None)

    resultado = ejecutar_solicitud(solicitud.id, "secreto")

    assert resultado["estado"] == "failed"
    db.session.expire_all()
    solicitud = db.session.get(CatalogRequest, solicitud.id)
    assert solicitud.status == "failed"
    assert db.session.execute(db.select(Job)).scalar_one_or_none() is None


def _exportar_seiscomp_falso(error=None):
    def exportar(inicio, fin, salida, log=None, progreso=None):
        if error:
            raise RuntimeError(error)
        shutil.copy2(
            SAMPLES / "seiscomp_20261001000000_20261031235959.csv",
            salida,
        )
        if progreso:
            progreso(1.0)
        return salida

    return exportar


def test_ejecutar_solicitud_exporta_seiscomp(app, monkeypatch):
    solicitud = _solicitud(
        app,
        fuentes=("eventquery", "seiscomp"),
        principal="seiscomp",
    )
    encolados = []
    monkeypatch.setattr(
        "app.services.acquisition._cargar_traer_catalogos",
        lambda: _traer_catalogos_falso(True),
    )
    monkeypatch.setattr(
        "app.services.acquisition.encolar_trabajo",
        lambda job_id: encolados.append(job_id),
    )
    llamado = {}

    def exportar(inicio, fin, salida, log=None, progreso=None):
        llamado["inicio"] = inicio
        llamado["fin"] = fin
        return _exportar_seiscomp_falso()(inicio, fin, salida, log, progreso)

    monkeypatch.setattr("app.services.seiscomp.exportar_ventana", exportar)

    resultado = ejecutar_solicitud(solicitud.id, "secreto")

    assert resultado["estado"] == "done"
    db.session.expire_all()
    job = db.session.execute(db.select(Job)).scalar_one()
    fuentes = {source.kind: source for source in job.sources}
    assert set(fuentes) == {"eventquery", "seiscomp"}
    assert fuentes["seiscomp"].role == "local_principal"
    assert fuentes["eventquery"].role == "referencia"
    assert {archivo.kind for archivo in job.files} == {"eventquery", "seiscomp"}
    assert llamado == {"inicio": INICIO, "fin": FIN}
    assert encolados == [job.id]


def test_ejecutar_solicitud_seiscomp_falla_no_crea_job(app, monkeypatch):
    solicitud = _solicitud(
        app,
        fuentes=("eventquery", "seiscomp"),
        principal="seiscomp",
    )
    monkeypatch.setattr(
        "app.services.acquisition._cargar_traer_catalogos",
        lambda: _traer_catalogos_falso(True),
    )
    monkeypatch.setattr("app.services.acquisition.encolar_trabajo", lambda _id: None)
    monkeypatch.setattr(
        "app.services.seiscomp.exportar_ventana",
        _exportar_seiscomp_falso("sin conexión a SeisComp"),
    )

    resultado = ejecutar_solicitud(solicitud.id, "secreto")

    assert resultado["estado"] == "failed"
    db.session.expire_all()
    solicitud = db.session.get(CatalogRequest, solicitud.id)
    assert solicitud.status == "failed"
    assert "sin conexión a SeisComp" in solicitud.error
    assert db.session.execute(db.select(Job)).scalar_one_or_none() is None


def test_reintentar_resetea_y_encola(client, login, app, monkeypatch):
    login()
    solicitud = _solicitud(app, status="failed")
    for archivo in solicitud.files:
        archivo.status = "error"
        archivo.message = "falló"
    db.session.commit()
    llamadas = []
    monkeypatch.setattr(
        "app.blueprints.solicitudes.encolar_solicitud",
        lambda request_id, password: llamadas.append((request_id, password)),
    )

    respuesta = client.post(
        f"/solicitudes/{solicitud.id}/reintentar",
        data={"password": "secreto"},
    )

    assert respuesta.status_code == 302
    db.session.expire_all()
    solicitud = db.session.get(CatalogRequest, solicitud.id)
    assert solicitud.status == "queued"
    assert all(archivo.status == "pending" for archivo in solicitud.files)
    assert llamadas == [(solicitud.id, "secreto")]


def test_reintentar_solo_creador_o_admin(client, app, monkeypatch):
    normal = User(username="normal", role="analista")
    normal.set_password("clave")
    db.session.add(normal)
    db.session.commit()
    solicitud = _solicitud(app, status="failed")
    monkeypatch.setattr("app.blueprints.solicitudes.encolar_solicitud", lambda *_: None)

    client.post("/login", data={"username": "normal", "password": "clave"})
    respuesta = client.post(f"/solicitudes/{solicitud.id}/reintentar", data={"password": "x"})

    assert respuesta.status_code == 403
