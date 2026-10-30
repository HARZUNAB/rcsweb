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


def _perfil_falso() -> dict:
    return {
        "id": "P001",
        "topo_p": [0.0, 100.0],
        "topo_alt": [0.0, 0.0],
        "slab_lon": [-71.0, -71.5],
        "slab_lat": [-30.0, -30.5],
        "slab_p": [0.0, 100.0],
        "slab_depth": [10.0, 20.0],
        "eventos": [],
    }


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
    assert "Descargar filtrado (1)" in html
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


def test_catalogo_eventquery_muestra_analista_probable(client, login):
    job = _job_con_tabla(login)
    workspace = ruta_workspace(job.id)
    datos_dir = workspace / "datos"
    datos_dir.mkdir(parents=True, exist_ok=True)
    (datos_dir / "new_2_eventquery.csv").write_text(
        ",Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Referencia,Percep.\n"
        "0,2026-10-03 15:53:56,-29.519,-72.594,30.0,2.8,ML,Coquimbo,S\n",
        encoding="utf-8",
    )
    (datos_dir / "atribucion_seisan.csv").write_text(
        "fecha_eventquery,lat_eventquery,lon_eventquery,analista,dt_seg,fuente\n"
        "2026-10-03 15:53:56,-29.519,-72.594,beto,0.0,seisan\n",
        encoding="utf-8",
    )
    (datos_dir / "atribucion_seiscomp.csv").write_text(
        "fecha_eventquery,lat_eventquery,lon_eventquery,analista,dt_seg,fuente\n"
        "2026-10-03 15:53:56,-29.519,-72.594,cris,0.0,seiscomp\n",
        encoding="utf-8",
    )
    ruta_indice = workspace / "resultados" / "indice.json"
    indice = json.loads(ruta_indice.read_text(encoding="utf-8"))
    indice["catalogos"]["eventquery"] = {
        "archivo": "datos/new_2_eventquery.csv",
        "filas": 1,
    }
    ruta_indice.write_text(json.dumps(indice), encoding="utf-8")

    html = client.get(
        f"/jobs/{job.id}/catalogos?catalogo=eventquery"
    ).get_data(as_text=True)
    assert "Analista probable" in html
    assert "SeisComp: cris" in html
    assert "Seisan: beto" in html

    detalle = client.get(
        f"/jobs/{job.id}/resultados/catalogos/eventquery/0"
    ).get_data(as_text=True)
    assert "Analista probable" in detalle
    assert "SeisComp: cris; Seisan: beto" in detalle


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
    assert "Sismo registrado" in html
    assert "plotly.min.js" in html
    assert "data-topojson-url" in html
    assert "perfil-contenedor" in html
    assert 'id="perfil-detalle"' in html
    assert "vineta.js" in html
    assert 'id="mapa-seleccion-perfil"' not in html
    assert '"clave"' in html
    assert "mapa_detalle.js" in html
    assert "Seisan" in html


def test_detalle_sin_perfil_muestra_aviso(client, login, monkeypatch):
    job = _job_con_tabla(login)
    monkeypatch.setattr(
        "app.blueprints.results.perfil_desde_eventos",
        lambda *args, **kwargs: None,
    )

    html = client.get(
        f"/jobs/{job.id}/resultados/no_publicados/seisan/0",
        query_string={"mapa": "offline"},
    ).get_data(as_text=True)

    assert "Perfil no disponible" in html
    assert 'id="perfil-detalle"' in html
    assert 'id="mostrar-historico"' not in html


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


def test_historico_se_activa_por_query(client, login, monkeypatch):
    job = _job_con_tabla(login)
    monkeypatch.setattr(
        "app.blueprints.results.perfil_desde_eventos",
        lambda *args, **kwargs: _perfil_falso(),
    )

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
    historico = json.loads(
        re.search(
            r'<script type="application/json" id="historico-datos">(.*?)</script>',
            con,
            re.S,
        ).group(1)
    )
    assert "planta" not in historico
    assert "perfil" in historico


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
    assert "Haga clic en un evento" in html


def test_tabla_muestra_minimapa_de_planta(client, login, monkeypatch):
    job = _job_con_tabla(login)
    monkeypatch.setattr(
        "app.blueprints.results.mapa_fila",
        lambda lat, lon: {
            "x": 50.0,
            "y": 70.0,
            "visible": True,
            "ubicacion": "Chile",
        },
    )

    html = client.get(
        f"/jobs/{job.id}/resultados/no-publicados",
        query_string={"fuente": "seisan"},
    ).get_data(as_text=True)

    assert "Ubicación" in html
    assert "data-toggle-miniaturas" in html
    assert "data-miniaturas-fila" in html
    assert "data-src=" in html
    assert "mapa-chile-mini" in html
    assert "minimapa-planta" in html
    assert 'cx="50.0"' in html
    assert "text-bg-success" in html
    assert "Chile" in html


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


def test_tabla_filtra_por_rango_numerico(client, login):
    job = _job_con_tabla(login)

    html = client.get(
        f"/jobs/{job.id}/resultados/no-publicados",
        query_string={
            "fuente": "seisan",
            "f_Mag.": "2..3",
        },
    ).get_data(as_text=True)

    assert "ana" in html
    assert "beto" not in html
    assert 'name="f_Mag."' in html
    assert 'value="2..3"' in html
    assert 'placeholder="Mín..Máx"' in html
    assert "Descargar filtrado (1)" in html


def test_tabla_ofrece_seleccion_y_descargas(client, login):
    job = _job_con_tabla(login)

    html = client.get(
        f"/jobs/{job.id}/resultados/no-publicados",
        query_string={"fuente": "seisan"},
    ).get_data(as_text=True)

    assert "Descargar todo" in html
    assert "Descargar filtrado" in html
    assert "Descargar seleccionados" in html
    assert "data-seleccionar-todos" in html
    assert "seleccion-evento" in html
    assert "data-descargar-seleccionados" in html
    assert "data-url-seleccionados" in html
    assert "tabla_seleccion.js" in html


def test_exportar_todo_ignora_filtros(client, login):
    job = _job_con_tabla(login)

    respuesta = client.get(
        f"/jobs/{job.id}/resultados/no_publicados/exportar",
        query_string={"fuente": "seisan", "f_Mag.": ">=3", "todo": "1"},
    )

    assert respuesta.status_code == 200
    texto = respuesta.data.decode("utf-8-sig")
    assert "ana" in texto
    assert "beto" in texto
    assert len([linea for linea in texto.splitlines() if linea.strip()]) == 3


def test_exportar_seleccionados(client, login):
    job = _job_con_tabla(login)

    respuesta = client.post(
        f"/jobs/{job.id}/resultados/no_publicados/exportar-seleccionados",
        query_string={"fuente": "seisan"},
        data={"filas": ["1"]},
    )

    assert respuesta.status_code == 200
    texto = respuesta.data.decode("utf-8-sig")
    assert "beto" in texto
    assert "ana" not in texto
    assert len([linea for linea in texto.splitlines() if linea.strip()]) == 2


def test_exportar_seleccionados_sin_filas_devuelve_400(client, login):
    job = _job_con_tabla(login)

    respuesta = client.post(
        f"/jobs/{job.id}/resultados/no_publicados/exportar-seleccionados",
        query_string={"fuente": "seisan"},
        data={},
    )

    assert respuesta.status_code == 400


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


def test_tabla_ofrece_enlace_al_catalogo_diario(client, login):
    job = _job_con_tabla(login)

    html = client.get(
        f"/jobs/{job.id}/resultados/no-publicados",
        query_string={"fuente": "seisan"},
    ).get_data(as_text=True)

    assert (
        "https://www.sismologia.cl/sismicidad/catalogo/2026/10/20261001.html"
        in html
    )
    assert "20261002" in html
    assert 'target="_blank"' in html
    assert 'rel="noopener"' in html


def test_tabla_repetidos_usa_la_ficha_compacta(client, login):
    job = _job_con_tabla(login)
    workspace = ruta_workspace(job.id)
    ruta = workspace / "resultados" / "repetidos_seisan_amplio.csv"
    ruta.write_text(
        "fecha_hora,latitud,longitud,prof,mag,tipomag,analista\n"
        "2026-10-01 00:00:00,-30.0,-71.0,10.0,2.5,ML,ana\n",
        encoding="utf-8",
    )
    indice_path = workspace / "resultados" / "indice.json"
    indice = json.loads(indice_path.read_text(encoding="utf-8"))
    indice["repetidos"] = {
        "seisan_amplio": {
            "archivo": "repetidos_seisan_amplio.csv",
            "filas": 1,
        }
    }
    indice_path.write_text(json.dumps(indice), encoding="utf-8")

    html = client.get(
        f"/jobs/{job.id}/resultados/repetidos",
        query_string={"clave": "seisan_amplio"},
    ).get_data(as_text=True)

    assert "Ubicación" in html
    assert "Perfil / Planta" not in html
    assert "data-toggle-miniaturas" in html
    assert "data-src=" in html


def _catalogo_seisan(client, login):
    job = _job_con_tabla(login)
    workspace = ruta_workspace(job.id)
    (workspace / "datos").mkdir(parents=True, exist_ok=True)
    (workspace / "datos" / "salida_collect.csv").write_text(
        ",Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista\n"
        "0,2026-10-01 00:00:00,-30.0,-71.0,10.0,3.0,ML,ana\n"
        "1,2026-10-02 00:00:00,-31.0,-72.0,20.0,4.0,ML,beto\n",
        encoding="utf-8",
    )
    indice_path = workspace / "resultados" / "indice.json"
    indice = json.loads(indice_path.read_text(encoding="utf-8"))
    indice["catalogos"] = {
        "seisan": {"archivo": "datos/salida_collect.csv", "filas": 2}
    }
    indice_path.write_text(json.dumps(indice), encoding="utf-8")
    return job


def test_catalogo_lista_con_las_mismas_prestaciones(client, login):
    job = _catalogo_seisan(client, login)

    html = client.get(
        f"/jobs/{job.id}/catalogos", query_string={"catalogo": "seisan"}
    ).get_data(as_text=True)

    assert "Catálogos" in html
    assert "Seisan" in html
    assert "Ubicación" in html
    assert "Descargar filtrado" in html
    assert "data-src=" in html
    assert "2026-10-01" in html
    assert (
        "https://www.sismologia.cl/sismicidad/catalogo/2026/10/20261001.html"
        in html
    )


def test_catalogo_detalle_de_evento(client, login):
    job = _catalogo_seisan(client, login)

    respuesta = client.get(
        f"/jobs/{job.id}/resultados/catalogos/seisan/0"
    )

    assert respuesta.status_code == 200
    html = respuesta.get_data(as_text=True)
    assert "Evento" in html
    assert "Fecha y hora" in html
    assert "ana" in html


def test_detalle_trabajo_muestra_menu_catalogos(client, login):
    job = _catalogo_seisan(client, login)

    html = client.get(f"/jobs/{job.id}").get_data(as_text=True)

    assert "Catálogos" in html
    assert "Paneles" in html
    assert f"/jobs/{job.id}/catalogos?catalogo=seisan" in html
    assert f"/jobs/{job.id}/paneles" in html


def test_catalogo_miniatura_y_mapa(client, login, monkeypatch):
    job = _catalogo_seisan(client, login)
    from app.blueprints import results as results_bp

    png = b"\x89PNG\r\n\x1a\n"
    monkeypatch.setattr(results_bp, "generar_miniatura", lambda *a, **k: png)
    monkeypatch.setattr(results_bp, "generar_mapa", lambda *a, **k: png)

    mini = client.get(
        f"/jobs/{job.id}/resultados/catalogos/seisan/0/miniatura.png"
    )
    mapa = client.get(f"/jobs/{job.id}/resultados/catalogos/seisan/0/mapa.png")

    assert mini.status_code == 200
    assert mini.data == png
    assert mapa.status_code == 200
    assert mapa.data == png


def test_catalogo_exporta_filtrado(client, login):
    job = _catalogo_seisan(client, login)

    respuesta = client.get(
        f"/jobs/{job.id}/resultados/catalogos/exportar",
        query_string={"catalogo": "seisan", "f_Analista": "ana"},
    )

    assert respuesta.status_code == 200
    assert respuesta.data.startswith(b"\xef\xbb\xbf")
    texto = respuesta.data.decode("utf-8-sig")
    assert "ana" in texto
    assert "beto" not in texto
