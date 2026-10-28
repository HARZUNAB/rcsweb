"""Pruebas de las rutas de tabla, filtros y exportación."""

from __future__ import annotations

from datetime import UTC, datetime

from app.extensions import db
from app.models import Job, nuevo_uuid
from app.services.workspace import crear_workspace


def _job_con_tabla(login):
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
    (workspace / "resultados" / "no_publicados_seisan.csv").write_text(
        ",Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista,"
        "Publicado_en,Estado,Dt_otra_seg,Dist_otra_km,Analista_otra\n"
        "0,2026-10-01 00:00:00,-30.000,-71.000,10.0,2.5,ML,ana,,Sin coincidencia,,,\n"
        "1,2026-10-02 00:00:00,-25.000,-70.000,20.0,3.5,ML,beto,,Sin coincidencia,,,\n",
        encoding="utf-8",
    )
    return job


def test_tabla_filtra_y_muestra_total(client, login):
    job = _job_con_tabla(login)

    respuesta = client.get(
        f"/jobs/{job.id}/resultados/no-publicados",
        query_string={"fuente": "seisan", "f_Mag.": ">=3"},
    )

    assert respuesta.status_code == 200
    html = respuesta.get_data(as_text=True)
    assert "beto" in html
    assert ">ana<" not in html
    assert "Exportar filtrado (1)" in html


def test_exportar_respeta_filtros(client, login):
    job = _job_con_tabla(login)

    respuesta = client.get(
        f"/jobs/{job.id}/resultados/no_publicados/exportar",
        query_string={"fuente": "seisan", "f_Mag.": ">=3"},
    )

    assert respuesta.status_code == 200
    assert respuesta.data.startswith(b"\xef\xbb\xbf")
    texto = respuesta.data.decode("utf-8-sig")
    lineas = [linea for linea in texto.splitlines() if linea.strip()]
    assert len(lineas) == 2
    assert "beto" in texto
    assert "ana" not in texto


def test_exportar_sin_datos_devuelve_404(client, login):
    login()
    job = Job(
        id=nuevo_uuid(),
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 31, tzinfo=UTC),
        status="done",
    )
    db.session.add(job)
    db.session.commit()

    respuesta = client.get(
        f"/jobs/{job.id}/resultados/no-publicados/exportar",
        query_string={"fuente": "seisan"},
    )

    assert respuesta.status_code == 404
