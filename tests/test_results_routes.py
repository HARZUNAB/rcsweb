"""Pruebas de las rutas de tabla, filtros y exportación."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from app.extensions import db
from app.models import Job, JobSource, nuevo_uuid
from app.services.workspace import crear_workspace, ruta_workspace


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


def _job_repetidos(login):
    job = _job_con_tabla(login)
    db.session.add_all(
        [
            JobSource(
                job_id=job.id,
                kind="seiscomp",
                alias="SeisComp",
                format="seiscomp",
                role="local_principal",
                priority=1,
            ),
            JobSource(
                job_id=job.id,
                kind="seisan",
                alias="Seisan",
                format="seisan",
                role="local_secundaria",
                priority=2,
            ),
        ]
    )
    db.session.commit()
    workspace = ruta_workspace(job.id)
    (workspace / "resultados" / "repetidos_publica_amplio.csv").write_text(
        "fecha_hora,latitud,longitud,prof,mag,tipomag,referencia,percibido,"
        "analista_seisan,analista_seiscomp\n"
        "2026-10-01 00:00:00,-30.000,-71.000,10.0,2.5,ML,Prueba,f,ana,beto\n",
        encoding="utf-8",
    )
    return job


def test_repetidos_agrupa_opciones(client, login):
    job = _job_repetidos(login)

    respuesta = client.get(
        f"/jobs/{job.id}/resultados/repetidos",
        query_string={"clave": "publica_amplio"},
    )

    assert respuesta.status_code == 200
    html = respuesta.get_data(as_text=True)
    assert "Publicados: Amplio" in html
    assert "SeisComp" in html
    assert "Seisan" in html
    assert "Excluidos" in html
    assert "dropdown-menu" in html
    assert "clave=publica_estricto" in html


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


def test_detalle_muestra_mapa_interactivo(client, login):
    job = _job_con_tabla(login)

    html = client.get(
        f"/jobs/{job.id}/resultados/no_publicados/seisan/0",
        query_string={"mapa": "offline"},
    ).get_data(as_text=True)

    assert 'id="mapa-detalle"' in html
    assert 'data-modo="offline"' in html
    assert 'id="mapa-datos"' in html
    assert "Mapa interactivo" in html
    assert "plotly.min.js" in html
    assert "data-topojson-url" in html
    assert "perfil-contenedor" in html
    assert 'id="mostrar-historico"' in html
    assert "Seisan" in html


def test_detalle_muestra_frontera_en_la_vineta(client, login, monkeypatch):
    job = _job_con_tabla(login)
    monkeypatch.setattr(
        "app.blueprints.results.texto_frontera_coords",
        lambda lat, lon: "Argentina — 12.0 km",
    )

    html = client.get(
        f"/jobs/{job.id}/resultados/no_publicados/seisan/0",
        query_string={"mapa": "offline"},
    ).get_data(as_text=True)

    assert "Frontera: Argentina — 12.0 km" in html
    datos = json.loads(
        re.search(
            r'<script type="application/json" id="mapa-datos">(.*?)</script>',
            html,
            re.S,
        ).group(1)
    )
    assert datos[0]["frontera"] == "Argentina — 12.0 km"


def test_tabla_muestra_columna_frontera(client, login, monkeypatch):
    job = _job_con_tabla(login)

    def _anotar(filas, lat, lon):
        for fila in filas:
            fila["Frontera_km"] = 12.0
            fila["Frontera"] = "Argentina — 12.0 km"
        return filas

    monkeypatch.setattr("app.services.results.borders.anotar_filas", _anotar)

    html = client.get(
        f"/jobs/{job.id}/resultados/no-publicados",
        query_string={"fuente": "seisan"},
    ).get_data(as_text=True)

    assert "Frontera más cercana" in html
    assert "Argentina — 12.0 km" in html


def test_historico_se_activa_por_query(client, login):
    job = _job_con_tabla(login)

    sin = client.get(
        f"/jobs/{job.id}/resultados/no_publicados/seisan/0",
        query_string={"mapa": "offline"},
    ).get_data(as_text=True)
    assert 'id="mostrar-historico"' in sin
    assert "checked" not in re.search(r'<input[^>]*id="mostrar-historico"[^>]*>', sin).group(0)
    assert 'id="historico-datos"' not in sin

    con = client.get(
        f"/jobs/{job.id}/resultados/no_publicados/seisan/0",
        query_string={"mapa": "offline", "historico": "1"},
    ).get_data(as_text=True)
    casilla = re.search(r'<input[^>]*id="mostrar-historico"[^>]*>', con).group(0)
    assert "checked" in casilla
    assert 'id="historico-datos"' in con
    assert "Sismicidad histórica" in con


def test_detalle_marca_evento_sospechoso(client, login, monkeypatch):
    job = _job_con_tabla(login)
    monkeypatch.setattr(
        "app.blueprints.results.clasificar_eventos",
        lambda *args: (
            [
                {
                    "latitud": -30.0,
                    "longitud": -71.0,
                    "sospechoso": True,
                }
            ],
            None,
        ),
    )

    html = client.get(
        f"/jobs/{job.id}/resultados/no_publicados/seisan/0",
        query_string={"mapa": "offline"},
    ).get_data(as_text=True)

    assert "Sospechoso (borde violeta)" in html
    datos = json.loads(
        re.search(
            r'<script type="application/json" id="mapa-datos">(.*?)</script>',
            html,
            re.S,
        ).group(1)
    )
    assert datos[0]["sospechoso"] is True


def test_repetidos_detalle_oculta_ver(client, login):
    job = _job_repetidos(login)

    html = client.get(
        f"/jobs/{job.id}/resultados/repetidos/publica_amplio/0",
        query_string={"mapa": "offline"},
    ).get_data(as_text=True)

    assert "data-href=" in html
    assert ">Ver</a>" not in html
    assert "Hacé clic en un evento" in html


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
