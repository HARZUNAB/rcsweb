"""Pruebas de roles, permisos y administración de usuarios."""

from __future__ import annotations

import json
import types
from datetime import UTC, datetime

import pytest

from app.extensions import db
from app.models import Job, User, nuevo_uuid
from app.security import alcance_total, etiqueta_rol, tiene_permiso
from app.services.workspace import crear_workspace


@pytest.fixture()
def usuarios(app):
    cuentas = {}
    for rol in ("supervisor", "analista", "consulta"):
        usuario = User(username=rol, role=rol)
        usuario.set_password("secret")
        db.session.add(usuario)
        cuentas[rol] = usuario
    db.session.commit()
    return cuentas


def _login(client, username: str, password: str = "secret"):
    client.post("/logout")
    return client.post(
        "/login",
        data={"username": username, "password": password},
    )


def _job(creador_id: int | None = None, estado: str = "done") -> Job:
    job = Job(
        id=nuevo_uuid(),
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 31, tzinfo=UTC),
        status=estado,
        created_by_id=creador_id,
    )
    db.session.add(job)
    db.session.commit()
    crear_workspace(job.id)
    return job


def _job_con_tabla(creador_id: int | None = None) -> Job:
    job = _job(creador_id)
    workspace = crear_workspace(job.id)
    (workspace / "resultados").mkdir(parents=True, exist_ok=True)
    (workspace / "resultados" / "no_publicados_seisan.csv").write_text(
        ",Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista,"
        "Publicado_en,Estado,Dt_otra_seg,Dist_otra_km,Analista_otra\n"
        "0,2026-10-01 00:00:00,-30.000,-71.000,10.0,2.5,ML,ana,,Sin coincidencia,,,\n",
        encoding="utf-8",
    )
    (workspace / "resultados" / "indice.json").write_text(
        json.dumps(
            {
                "no_publicados": {
                    "seisan": {
                        "archivo": "no_publicados_seisan.csv",
                        "filas": 1,
                    }
                },
                "no_actualizados": {},
                "repetidos": {},
                "catalogos": {},
            }
        ),
        encoding="utf-8",
    )
    return job


@pytest.mark.parametrize(
    ("rol", "permiso", "esperado"),
    [
        ("admin", "usuarios.gestionar", True),
        ("admin", "auditoria.ver", True),
        ("supervisor", "usuarios.gestionar", False),
        ("supervisor", "auditoria.ver", True),
        ("supervisor", "trabajos.eliminar", True),
        ("supervisor", "trabajos.todos", True),
        ("analista", "auditoria.ver", False),
        ("analista", "trabajos.eliminar", True),
        ("analista", "trabajos.todos", False),
        ("analista", "resultados.exportar", True),
        ("consulta", "trabajos.ver", True),
        ("consulta", "paneles.ver", True),
        ("consulta", "catalogos.ver", True),
        ("consulta", "trabajos.crear", False),
        ("consulta", "resultados.exportar", False),
        ("desconocido", "trabajos.ver", False),
    ],
)
def test_matriz_de_permisos(rol, permiso, esperado):
    usuario = types.SimpleNamespace(is_authenticated=True, role=rol)
    assert tiene_permiso(usuario, permiso) is esperado


def test_etiquetas_y_alcance():
    assert etiqueta_rol("supervisor") == "Supervisor"
    assert etiqueta_rol("admin") == "Administrador"
    assert alcance_total(types.SimpleNamespace(is_authenticated=True, role="supervisor"))
    assert not alcance_total(
        types.SimpleNamespace(is_authenticated=True, role="analista")
    )


def test_consulta_es_solo_lectura(client, usuarios):
    _login(client, "consulta")
    assert client.get("/").status_code == 200
    assert client.get("/jobs/new/subir").status_code == 403
    assert client.get("/solicitudes/nueva").status_code == 403
    assert client.get("/admin/auditoria").status_code == 403
    assert client.get("/admin/usuarios").status_code == 403


def test_supervisor_ve_auditoria_pero_no_usuarios(client, usuarios):
    _login(client, "supervisor")
    assert client.get("/admin/auditoria").status_code == 200
    assert client.get("/admin/usuarios").status_code == 403
    assert client.get("/jobs/new/subir").status_code == 200


def test_admin_ve_usuarios(client, usuarios):
    _login(client, "tester")
    assert client.get("/admin/usuarios").status_code == 200
    assert client.get("/admin/auditoria").status_code == 200


def test_navegacion_segun_rol(client, usuarios):
    _login(client, "consulta")
    html = client.get("/").get_data(as_text=True)
    assert "Nuevo trabajo" not in html
    assert "Solicitar catálogos" not in html
    assert ">Solicitudes<" not in html
    assert "Auditoría" not in html
    assert "Usuarios" not in html
    assert "Consulta" in html

    _login(client, "supervisor")
    html = client.get("/").get_data(as_text=True)
    assert "Nuevo trabajo" in html
    assert "Solicitar catálogos" not in html
    assert "Auditoría" in html
    assert ">Usuarios<" not in html
    assert "Supervisor" in html

    _login(client, "analista")
    html = client.get("/").get_data(as_text=True)
    assert "Nuevo trabajo" in html
    assert ">Solicitudes<" not in html
    assert "Auditoría" not in html
    assert ">Usuarios<" not in html


def test_consulta_no_exporta_ni_descarga(client, usuarios):
    job = _job_con_tabla(usuarios["consulta"].id)
    _login(client, "consulta")
    html = client.get(
        f"/jobs/{job.id}/resultados/no-publicados",
        query_string={"fuente": "seisan"},
    ).get_data(as_text=True)
    assert "Descargar todo" not in html
    assert "Descargar filtrado" not in html
    assert "Descargar seleccionados" not in html
    assert client.get(
        f"/jobs/{job.id}/resultados/no_publicados/exportar",
        query_string={"fuente": "seisan"},
    ).status_code == 403
    assert client.get(f"/jobs/{job.id}/descargas").status_code == 403


def test_analista_exporta_su_trabajo(client, usuarios):
    _login(client, "analista")
    job = _job_con_tabla(usuarios["analista"].id)
    html = client.get(
        f"/jobs/{job.id}/resultados/no-publicados",
        query_string={"fuente": "seisan"},
    ).get_data(as_text=True)
    assert "Descargar todo" in html
    assert "Descargar filtrado" in html
    respuesta = client.get(
        f"/jobs/{job.id}/resultados/no_publicados/exportar",
        query_string={"fuente": "seisan"},
    )
    assert respuesta.status_code == 200
    assert respuesta.data.startswith(b"\xef\xbb\xbf")
    assert client.get(f"/jobs/{job.id}").status_code == 200


def test_analista_elimina_y_cancela_lo_propio(client, usuarios):
    _login(client, "analista")
    usuario = usuarios["analista"]
    job = _job(usuario.id, estado="queued")
    assert client.post(f"/jobs/{job.id}/cancelar").status_code == 302
    assert db.session.get(Job, job.id).status == "cancelled"

    otro = _job(usuario.id)
    assert client.post(f"/jobs/{otro.id}/eliminar").status_code == 302
    assert db.session.get(Job, otro.id) is None


def test_supervisor_elimina_y_cancela_ajenos(client, usuarios):
    _login(client, "supervisor")
    job = _job(None, estado="queued")
    assert client.post(f"/jobs/{job.id}/cancelar").status_code == 302
    assert db.session.get(Job, job.id).status == "cancelled"

    otro = _job(None)
    assert client.post(f"/jobs/{otro.id}/eliminar").status_code == 302
    assert db.session.get(Job, otro.id) is None


def test_job_detail_oculta_descargas_para_consulta(client, usuarios):
    job = _job_con_tabla(usuarios["consulta"].id)
    _login(client, "consulta")
    html = client.get(f"/jobs/{job.id}").get_data(as_text=True)
    assert "Descargas" not in html
    assert "Eliminar" not in html


def test_admin_crea_usuario_y_cambia_rol(client, usuarios):
    _login(client, "tester")
    respuesta = client.post(
        "/admin/usuarios/crear",
        data={
            "username": "nuevo",
            "role": "supervisor",
            "password": "clave12345",
            "confirm_password": "clave12345",
            "active": "y",
        },
    )
    assert respuesta.status_code == 302
    creado = db.session.execute(
        db.select(User).filter_by(username="nuevo")
    ).scalar_one()
    assert creado.role == "supervisor"
    assert creado.active is True
    assert creado.check_password("clave12345")

    respuesta = client.post(
        f"/admin/usuarios/{creado.id}/rol",
        data={
            "role": "consulta",
            "active": "y",
            "analyst_code": "Nuevo",
        },
    )
    assert respuesta.status_code == 302
    assert db.session.get(User, creado.id).role == "consulta"

    respuesta = client.post(
        f"/admin/usuarios/{creado.id}/password",
        data={
            "new_password": "otraclave123",
            "confirm_password": "otraclave123",
        },
    )
    assert respuesta.status_code == 302
    assert db.session.get(User, creado.id).check_password("otraclave123")

    _login(client, "nuevo", "otraclave123")
    assert client.get("/").status_code == 200


def test_admin_exige_codigo_a_analista(client, usuarios):
    _login(client, "tester")
    respuesta = client.post(
        "/admin/usuarios/crear",
        data={
            "username": "sin-codigo",
            "role": "analista",
            "password": "clave12345",
            "confirm_password": "clave12345",
            "active": "y",
        },
        follow_redirects=True,
    )

    assert respuesta.status_code == 200
    assert "código de analista" in respuesta.get_data(as_text=True).lower()
    assert (
        db.session.execute(
            db.select(User).filter_by(username="sin-codigo")
        ).scalar_one_or_none()
        is None
    )


def test_cli_asigna_codigo_de_analista(app, usuarios):
    runner = app.test_cli_runner()

    resultado = runner.invoke(
        args=["set-analyst-code", "consulta", "Cons", "--aliases", "Consu"]
    )

    assert resultado.exit_code == 0, resultado.output
    db.session.expire_all()
    consulta = db.session.execute(
        db.select(User).filter_by(username="consulta")
    ).scalar_one()
    assert consulta.analyst_code == "Cons"
    assert consulta.analyst_aliases == "Consu"


def test_no_se_puede_dejar_sin_administradores(client, usuarios):
    _login(client, "tester")
    admin = db.session.execute(
        db.select(User).filter_by(username="tester")
    ).scalar_one()
    respuesta = client.post(
        f"/admin/usuarios/{admin.id}/rol",
        data={"role": "consulta", "active": "y"},
        follow_redirects=True,
    )
    assert respuesta.status_code == 200
    assert db.session.get(User, admin.id).role == "admin"
    assert "al menos un administrador" in respuesta.get_data(as_text=True)


def test_usuario_desactivado_pierde_la_sesion(client, usuarios):
    _login(client, "consulta")
    usuario = usuarios["consulta"]
    usuario.active = False
    db.session.commit()
    respuesta = client.get("/")
    assert respuesta.status_code == 302
    assert "/login" in respuesta.headers["Location"]


def test_cli_roles_y_password(app, usuarios):
    runner = app.test_cli_runner()
    resultado = runner.invoke(args=["set-role", "consulta", "supervisor"])
    assert resultado.exit_code == 0
    assert db.session.execute(
        db.select(User).filter_by(username="consulta")
    ).scalar_one().role == "supervisor"

    resultado = runner.invoke(
        args=["reset-password", "consulta"],
        input="nueva12345\nnueva12345\n",
    )
    assert resultado.exit_code == 0
    assert db.session.execute(
        db.select(User).filter_by(username="consulta")
    ).scalar_one().check_password("nueva12345")

    resultado = runner.invoke(args=["list-users"])
    assert resultado.exit_code == 0
    assert "consulta" in resultado.output
    assert "Supervisor" in resultado.output


def test_analista_no_entra_a_auditoria(client, usuarios):
    _login(client, "analista")
    assert client.get("/admin/auditoria").status_code == 403


def test_recuperar_acceso_es_publico_y_orienta(client):
    html = client.get("/recuperar").get_data(as_text=True)
    assert "Recuperar acceso" in html
    assert "reset-password" in html
    login = client.get("/login").get_data(as_text=True)
    assert "¿Olvidó su contraseña?" in login


def test_analista_no_ve_trabajo_ajeno(client, usuarios):
    admin = db.session.execute(
        db.select(User).filter_by(username="tester")
    ).scalar_one()
    job = _job(admin.id)
    _login(client, "analista")
    html = client.get("/").get_data(as_text=True)
    assert job.id not in html
    assert client.get(f"/jobs/{job.id}").status_code == 403
    assert client.get(f"/jobs/{job.id}/resultados").status_code == 403
    assert client.get(f"/jobs/{job.id}/paneles").status_code == 403
    assert client.post(f"/jobs/{job.id}/eliminar").status_code == 403
    assert client.post(f"/jobs/{job.id}/cancelar").status_code == 403


def test_admin_ve_trabajo_ajeno_y_creador(client, usuarios):
    analista = usuarios["analista"]
    job = _job(analista.id)
    _login(client, "tester")
    html = client.get("/").get_data(as_text=True)
    assert job.id in html
    assert "Creador" in html
    assert "analista" in html
    assert client.get(f"/jobs/{job.id}").status_code == 200


def test_consulta_ve_solo_su_trabajo(client, usuarios):
    consulta = usuarios["consulta"]
    job = _job(consulta.id)
    _login(client, "consulta")
    html = client.get("/").get_data(as_text=True)
    assert job.id in html
    assert client.get(f"/jobs/{job.id}").status_code == 200
    assert client.post(f"/jobs/{job.id}/eliminar").status_code == 403
