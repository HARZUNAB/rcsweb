"""Acceso por analista en Resultados, Catálogos y descargas."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from app.extensions import db
from app.models import Job, User, nuevo_uuid
from app.services.workspace import crear_workspace


def _usuario(username, code, role="analista"):
    usuario = User(
        username=username,
        role=role,
        analyst_code=code,
        active=True,
    )
    usuario.set_password("secret")
    db.session.add(usuario)
    db.session.commit()
    return usuario


def _job(creador_id):
    job = Job(
        id=nuevo_uuid(),
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 31, tzinfo=UTC),
        status="done",
        created_by_id=creador_id,
    )
    db.session.add(job)
    db.session.commit()
    return job


def _preparar(app, usuario):
    job = _job(usuario.id)
    workspace = crear_workspace(job.id)
    resultados = workspace / "resultados"
    resultados.mkdir(parents=True, exist_ok=True)
    cabecera = (
        ",Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista,"
        "Publicado_en,Estado,Dt_otra_seg,Dist_otra_km,Analista_otra\n"
    )
    filas = (
        "0,2026-10-01 00:00:00,-30.0,-71.0,10.0,2.5,ML,ana,,Sin coincidencia,,,\n"
        "1,2026-10-02 00:00:00,-31.0,-72.0,20.0,3.5,ML,beto,,Sin coincidencia,,,\n"
    )
    (resultados / "no_publicados_seisan.csv").write_text(
        cabecera + filas, encoding="utf-8"
    )
    (resultados / "catalogo_seisan.csv").write_text(
        "Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista,Referencia\n"
        "2026-10-01 00:00:00,-30.0,-71.0,10.0,2.5,ML,ana,Coquimbo\n"
        "2026-10-02 00:00:00,-31.0,-72.0,20.0,3.5,ML,beto,Valparaíso\n",
        encoding="utf-8",
    )
    (resultados / "indice.json").write_text(
        json.dumps(
            {
                "no_publicados": {
                    "seisan": {
                        "archivo": "no_publicados_seisan.csv",
                        "filas": 2,
                    }
                },
                "no_actualizados": {},
                "repetidos": {},
                "catalogos": {
                    "seisan": {
                        "archivo": "resultados/catalogo_seisan.csv",
                        "filas": 2,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return job


def _login(client, username):
    client.post("/logout")
    return client.post(
        "/login", data={"username": username, "password": "secret"}
    )


def test_analista_solo_ve_sus_filas_en_resultados(app, client):
    ana = _usuario("ana", "ana")
    _usuario("beto", "beto")
    job = _preparar(app, ana)
    _login(client, "ana")

    html = client.get(
        f"/jobs/{job.id}/resultados/no-publicados",
        query_string={"fuente": "seisan"},
    ).get_data(as_text=True)

    assert "ana" in html
    assert "beto" not in html
    assert "Mostrando 1–1 de 1" in html


def test_admin_ve_todas_las_filas_de_resultados(app, client):
    ana = _usuario("ana", "ana")
    _usuario("beto", "beto")
    job = _preparar(app, ana)
    _login(client, "tester")

    html = client.get(
        f"/jobs/{job.id}/resultados/no-publicados",
        query_string={"fuente": "seisan"},
    ).get_data(as_text=True)

    assert "ana" in html
    assert "beto" in html


def test_analista_no_abre_detalle_ajeno(app, client):
    ana = _usuario("ana", "ana")
    _usuario("beto", "beto")
    job = _preparar(app, ana)
    _login(client, "ana")

    propio = client.get(
        f"/jobs/{job.id}/resultados/no_publicados/seisan/0"
    )
    ajeno = client.get(
        f"/jobs/{job.id}/resultados/no_publicados/seisan/1"
    )

    assert propio.status_code == 200
    assert ajeno.status_code == 403


def test_catalogos_analista_global_sin_columnas_de_analista(app, client):
    ana = _usuario("ana", "ana")
    _usuario("beto", "beto")
    job = _preparar(app, ana)
    _login(client, "ana")

    html = client.get(
        f"/jobs/{job.id}/catalogos",
        query_string={"catalogo": "seisan"},
    ).get_data(as_text=True)

    assert "Coquimbo" in html
    assert "Valparaíso" in html
    assert 'name="f_Analista"' not in html
    assert "Descargar catálogo" in html
    assert "Descargar todo" not in html
    assert "Descargar filtrado" not in html
    assert "Descargar seleccionados" not in html
    assert 'title="Abrir el catálogo diario de sismologia.cl"' not in html
    assert ">Ver</a>" not in html
    assert "Ver miniaturas" not in html


def test_catalogos_admin_mantiene_columnas_y_botones(app, client):
    ana = _usuario("ana", "ana")
    _usuario("beto", "beto")
    job = _preparar(app, ana)
    _login(client, "tester")

    html = client.get(
        f"/jobs/{job.id}/catalogos",
        query_string={"catalogo": "seisan"},
    ).get_data(as_text=True)

    assert 'name="f_Analista"' in html
    assert "Descargar catálogo" in html
    assert "Descargar todo" in html
    assert 'title="Abrir el catálogo diario de sismologia.cl"' in html
    assert "Ver miniaturas" in html


def test_catalogo_nuevo_csv_sanitizado_y_sin_analista(app, client):
    ana = _usuario("ana", "ana")
    _usuario("beto", "beto")
    job = _preparar(app, ana)
    _login(client, "ana")

    preview = client.get(
        f"/jobs/{job.id}/resultados/catalogos/seisan/catalogo"
    )
    assert preview.status_code == 200
    assert "Descargar CSV" in preview.get_data(as_text=True)
    assert "Descargar ZIP" in preview.get_data(as_text=True)

    respuesta = client.get(
        f"/jobs/{job.id}/resultados/catalogos/seisan/catalogo.csv"
    )
    assert respuesta.status_code == 200
    texto = respuesta.get_data(as_text=True)
    assert "Fecha y hora,Latitud,Longitud,Prof. (km),Mag.,Tipo mag.,Referencia geográfica" in texto
    assert "ana" not in texto
    assert "beto" not in texto
    assert "Coquimbo" in texto
    assert "Valparaíso" in texto


def test_consulta_solo_tiene_descargar_catalogo(app, client):
    consulta = _usuario("consulta", "cons", role="consulta")
    _usuario("beto", "beto")
    job = _preparar(app, consulta)
    _login(client, "consulta")

    html = client.get(
        f"/jobs/{job.id}/catalogos",
        query_string={"catalogo": "seisan"},
    ).get_data(as_text=True)

    assert "Descargar catálogo" in html
    assert "Descargar todo" not in html
    assert "Descargar filtrado" not in html
    assert "Descargar seleccionados" not in html
    assert 'title="Abrir el catálogo diario de sismologia.cl"' not in html
    assert "Ver miniaturas" not in html
    assert client.get(
        f"/jobs/{job.id}/resultados/catalogos/exportar",
        query_string={"catalogo": "seisan", "todo": "1"},
    ).status_code == 403


def test_catalogo_zip_incluye_csv_y_mapa(app, client, monkeypatch):
    ana = _usuario("ana", "ana")
    _usuario("beto", "beto")
    job = _preparar(app, ana)
    _login(client, "ana")
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    monkeypatch.setattr(
        "app.services.catalog_export.mapa_planta",
        lambda *args, **kwargs: png,
    )
    monkeypatch.setattr(
        "app.services.catalog_export.mapa_perfil",
        lambda *args, **kwargs: None,
    )

    respuesta = client.get(
        f"/jobs/{job.id}/resultados/catalogos/seisan/catalogo.zip"
    )

    assert respuesta.status_code == 200
    assert respuesta.mimetype == "application/zip"
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(respuesta.data)) as archivo:
        assert "catalogo.csv" in archivo.namelist()
        assert "planta_nacional.png" in archivo.namelist()
        csv = archivo.read("catalogo.csv").decode("utf-8-sig")
        assert "ana" not in csv
        assert "beto" not in csv


def test_analista_sin_codigo_no_accede_a_catalogos(app, client):
    ana = _usuario("sin-codigo", None)
    _usuario("beto", "beto")
    job = _preparar(app, ana)
    _login(client, "sin-codigo")

    respuesta = client.get(
        f"/jobs/{job.id}/catalogos",
        query_string={"catalogo": "seisan"},
    )

    assert respuesta.status_code == 403


def test_catalogo_analista_no_accede_al_detalle_ni_exportacion_completa(app, client):
    ana = _usuario("ana", "ana")
    _usuario("beto", "beto")
    job = _preparar(app, ana)
    _login(client, "ana")

    assert client.get(
        f"/jobs/{job.id}/resultados/catalogos/seisan/0"
    ).status_code == 403
    assert client.get(
        f"/jobs/{job.id}/resultados/catalogos/exportar",
        query_string={"catalogo": "seisan", "todo": "1"},
    ).status_code == 403
