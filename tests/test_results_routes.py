"""Pruebas de las rutas de tabla, filtros y exportación."""

from __future__ import annotations

import json
import re
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
    (workspace / "resultados" / "indice.json").write_text(
        json.dumps(
            {
                "no_publicados": {"seisan": {"archivo": "no_publicados_seisan.csv", "filas": 2}},
                "no_actualizados": {},
                "repetidos": {},
                "catalogos": {"seisan": {"archivo": "datos/salida_collect.csv", "filas": 4}},
            }
        ),
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
    assert "catálogo: 4" in html


def test_volver_de_tabla_lleva_al_trabajo(client, login):
    job = _job_con_tabla(login)

    html = client.get(
        f"/jobs/{job.id}/resultados/no-publicados",
        query_string={"fuente": "seisan"},
    ).get_data(as_text=True)

    boton = re.search(r'<a class="btn[^"]*" href="([^"]+)">Volver al trabajo</a>', html)
    assert boton
    assert boton.group(1) == f"/jobs/{job.id}"


def test_overview_redirige_al_trabajo(client, login):
    job = _job_con_tabla(login)

    respuesta = client.get(f"/jobs/{job.id}/resultados")

    assert respuesta.status_code == 302
    assert respuesta.headers["Location"].endswith(f"/jobs/{job.id}#resultados")


def test_detalle_fila_ofrece_volver_al_trabajo(client, login):
    job = _job_con_tabla(login)

    html = client.get(f"/jobs/{job.id}/resultados/no_publicados/seisan/0").get_data(as_text=True)

    assert "Volver al trabajo" in html
    assert "Volver a la tabla" in html
    assert f'href="/jobs/{job.id}"' in html


def test_detalle_trabajo_muestra_catalogos(client, login):
    job = _job_con_tabla(login)

    html = client.get(f"/jobs/{job.id}").get_data(as_text=True)

    assert 'id="resultados"' in html
    assert 'href="#resultados"' in html
    assert "Catálogos procesados" in html
    assert f'href="/jobs/{job.id}/resultados"' not in html


def test_descargas_muestra_catalogos(client, login):
    job = _job_con_tabla(login)

    html = client.get(f"/jobs/{job.id}/descargas").get_data(as_text=True)

    assert "Catálogos procesados" in html
    assert "4</strong> eventos" in html


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
