"""Pruebas de los paneles por perfil y de la agrupación por territorios."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from app.extensions import db
from app.models import Job, nuevo_uuid
from app.services import panels, plots
from app.services.workspace import crear_workspace, ruta_workspace


def _job() -> Job:
    job = Job(
        id=nuevo_uuid(),
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 31, tzinfo=UTC),
        status="done",
    )
    db.session.add(job)
    db.session.commit()
    crear_workspace(job.id)
    return job


def _perfil_sintetico() -> dict:
    return {
        "id": "P001",
        "lat_media": -30.0,
        "slab": {
            "p": [0, 100, 200],
            "depth": [10, 20, 30],
            "lat": [-30, -30.5, -31],
            "lon": [-71, -71.5, -72],
        },
        "topo_p": [0, 100, 200],
        "topo_alt": [0, 1000, 0],
    }


def _asignacion_falsa(monkeypatch):
    def _asignar(eventos):
        for evento in eventos:
            if evento["lat"] > -35:
                evento["perfil"] = "P001"
                evento["along_km"] = 50.0
                evento["sospechoso"] = False
            else:
                evento["perfil"] = None
                evento["sospechoso"] = True
        return eventos, [_perfil_sintetico()]

    monkeypatch.setattr(panels, "_asignar", _asignar)
    monkeypatch.setattr(plots, "_perfiles", lambda: [_perfil_sintetico()])


def test_panel_catalogo_agrupa_por_perfil_y_territorio(app, monkeypatch):
    _asignacion_falsa(monkeypatch)
    job = _job()
    workspace = ruta_workspace(job.id)
    (workspace / "datos").mkdir(parents=True, exist_ok=True)
    (workspace / "datos" / "seiscomp_parametros.csv").write_text(
        ",Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista\n"
        "0,2026-10-01 00:00:00,-30.0,-71.0,30.0,3.0,ML,ana\n"
        "1,2026-10-02 00:00:00,-40.0,-100.0,20.0,3.5,ML,beto\n",
        encoding="utf-8",
    )
    (workspace / "resultados").mkdir(parents=True, exist_ok=True)
    (workspace / "resultados" / "indice.json").write_text(
        json.dumps(
            {
                "catalogos": {
                    "seiscomp": {
                        "archivo": "datos/seiscomp_parametros.csv",
                        "filas": 2,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    datos = panels.cargar(workspace, "catalogo_seiscomp")

    assert datos["total"] == 2
    assert datos["con_perfil"] == 1
    assert datos["sin_perfil"] == 1
    assert datos["perfiles"][0]["id"] == "P001"
    assert datos["territorios"][0]["nombre"] == "Otros"


def test_panel_observaciones_deduplica_repetidos(app, monkeypatch):
    _asignacion_falsa(monkeypatch)
    job = _job()
    workspace = ruta_workspace(job.id)
    resultados = workspace / "resultados"
    resultados.mkdir(parents=True, exist_ok=True)

    (resultados / "no_publicados_seisan.csv").write_text(
        "Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista\n"
        "2026-10-01 00:00:00,-30.0,-71.0,30.0,3.0,ML,ana\n",
        encoding="utf-8",
    )
    (resultados / "no_actualizados_seiscomp.csv").write_text(
        "fecha_local,lat_local,lon_local,prof_local,mag_local,"
        "tipo_mag_local,revision,publicacion_probable\n"
        "2026-10-02 00:00:00,-31.0,-71.5,20.0,4.0,ML,Alta,Esta fuente\n",
        encoding="utf-8",
    )
    filas_repetidas = (
        "fecha_hora,latitud,longitud,prof,mag,tipomag,analista\n"
        "2026-10-03 00:00:00,-32.0,-72.0,15.0,3.2,ML,ana\n"
        "2026-10-03 00:00:01,-32.001,-72.001,15.0,3.1,ML,beto\n"
    )
    (resultados / "repetidos_seisan_amplio.csv").write_text(
        filas_repetidas, encoding="utf-8"
    )
    (resultados / "repetidos_seisan_estricto.csv").write_text(
        filas_repetidas, encoding="utf-8"
    )

    datos = panels.cargar(workspace, "observaciones")

    assert datos["total"] == 4  # 1 no publicado + 1 no actualizado + 2 repetidos únicos
    tipos = [evento["tipo_observacion"] for evento in datos["eventos"]]
    assert tipos.count("no_publicado") == 1
    assert tipos.count("no_actualizado") == 1
    assert tipos.count("repetido") == 2
    repetido = next(e for e in datos["eventos"] if e["tipo_observacion"] == "repetido")
    assert set(repetido["informes"]) == {"seisan_amplio", "seisan_estricto"}


def test_ruta_paneles_renderiza_el_resumen(client, login, monkeypatch):
    _asignacion_falsa(monkeypatch)
    job = _job()
    workspace = ruta_workspace(job.id)
    resultados = workspace / "resultados"
    resultados.mkdir(parents=True, exist_ok=True)
    (resultados / "no_publicados_seisan.csv").write_text(
        "Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista\n"
        "2026-10-01 00:00:00,-30.0,-71.0,30.0,3.0,ML,ana\n",
        encoding="utf-8",
    )
    login()

    respuesta = client.get(f"/jobs/{job.id}/paneles?dataset=observaciones")

    assert respuesta.status_code == 200
    html = respuesta.get_data(as_text=True)
    assert "Contexto sismotectónico" in html
    assert "Resultados" in html
    assert "P001" in html
    assert "No publicado" in html
    assert "panel-mapa" in html
    assert "panel-perfil-col" in html
    assert 'id="panel-grupos"' in html
    assert 'id="panel-perfil-vacio"' in html
    assert "Perfil no disponible" in html
    assert "vineta.js" in html
    assert 'id="panel-historico"' in html
    assert 'id="panel-historico-estado"' in html
    assert 'data-url-historico=' in html
    assert "Sismo no percibido / registrado" in html
    assert "Soluciones superpuestas" in html
    assert 'id="panel-seleccionar-todos"' in html
    assert 'id="panel-descargar-todo"' in html
    assert 'id="panel-descargar-filtrado"' in html
    assert 'id="panel-descargar-seleccionados"' in html
    assert 'id="panel-seleccionados-count"' in html
    assert 'id="panel-evento-detalle"' in html
    assert 'id="panel-evento-contenido"' in html
    assert 'id="panel-cerrar-evento"' in html
    assert 'data-job-id=' in html
    assert '"slab_lon"' in html
    assert '"lat"' in html


def test_filtrar_recalcula_resumenes():
    eventos = [
        {
            "perfil": "P001",
            "territorio": None,
            "lat": -30.0,
            "lon": -71.0,
            "along_km": 50.0,
            "tipo_observacion": "no_publicado",
            "fuente": "seisan",
            "sospechoso": True,
            "revision": "",
        },
        {
            "perfil": "P001",
            "territorio": None,
            "lat": -31.0,
            "lon": -71.5,
            "along_km": 60.0,
            "tipo_observacion": "no_actualizado",
            "fuente": "seiscomp",
            "sospechoso": False,
            "revision": "Alta",
        },
        {
            "perfil": None,
            "territorio": "Nacional",
            "lat": -40.0,
            "lon": -100.0,
            "along_km": None,
            "tipo_observacion": "no_publicado",
            "fuente": "seiscomp",
            "sospechoso": False,
            "revision": "",
        },
    ]
    datos = {"eventos": eventos, "total": 3, "perfiles": [], "territorios": []}

    filtrado = panels.filtrar(datos, "no_publicado", "seiscomp")

    assert filtrado["total"] == 1
    assert filtrado["con_perfil"] == 0
    assert filtrado["sin_perfil"] == 1
    assert filtrado["perfiles"] == []
    assert filtrado["territorios"][0]["nombre"] == "Nacional"
    assert filtrado["territorios"][0]["no_publicados"] == 1
    assert len(filtrado["eventos"]) == 1
    assert filtrado["eventos"][0]["fuente"] == "seiscomp"


def test_conteos_por_tipo_y_fuente():
    eventos = [
        {"tipo_observacion": "no_publicado", "fuente": "seisan"},
        {"tipo_observacion": "no_publicado", "fuente": "seiscomp"},
        {"tipo_observacion": "no_actualizado", "fuente": "seiscomp"},
    ]

    conteos = panels.conteos({"eventos": eventos})

    assert conteos["tipos"] == {
        "no_publicado": 2,
        "no_actualizado": 1,
        "repetido": 0,
    }
    assert conteos["fuentes_por_tipo"]["no_publicado"] == {
        "seisan": 1,
        "seiscomp": 1,
    }
    assert conteos["fuentes_todos"] == {"seisan": 1, "seiscomp": 2}


def test_ruta_paneles_filtra_por_tipo_y_fuente(client, login, monkeypatch):
    _asignacion_falsa(monkeypatch)
    job = _job()
    workspace = ruta_workspace(job.id)
    resultados = workspace / "resultados"
    resultados.mkdir(parents=True, exist_ok=True)
    (resultados / "no_publicados_seisan.csv").write_text(
        "Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista\n"
        "2026-10-01 00:00:00,-30.0,-71.0,30.0,3.0,ML,ana\n",
        encoding="utf-8",
    )
    (resultados / "no_publicados_seiscomp.csv").write_text(
        "Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista\n"
        "2026-10-02 00:00:00,-31.0,-71.5,20.0,3.5,ML,beto\n",
        encoding="utf-8",
    )
    login()

    respuesta = client.get(
        f"/jobs/{job.id}/paneles",
        query_string={
            "dataset": "observaciones",
            "tipo": "no_publicado",
            "fuente": "seiscomp",
        },
    )

    assert respuesta.status_code == 200
    html = respuesta.get_data(as_text=True)
    assert 'data-scroll="1"' in html
    assert "Ir al listado" in html
    assert "Volver a los paneles" in html
    assert "Fuente" in html
    assert "Tipo" in html
    assert "Filtro:" in html
    assert "data-url-regiones=" in html
    assert 'id="panel-centrar-mapa"' in html
    # Eventquery es la referencia y no aparece como fuente de Observaciones.
    assert "fuente=eventquery" not in html
    assert '<span class="btn btn-sm btn-outline-secondary disabled"' not in html
    assert 'id="panel-perfil-detalle"' in html
    assert "SeisComp" in html
    assert "Seisan" in html
    datos = json.loads(
        re.search(
            r'<script type="application/json" id="panel-datos">(.*?)</script>',
            html,
            re.S,
        ).group(1)
    )
    assert datos["total"] == 1
    assert datos["eventos"][0]["fuente"] == "seiscomp"
    assert datos["eventos"][0]["tipo_observacion"] == "no_publicado"


def test_ruta_paneles_cuenta_tipos_para_la_fuente(client, login, monkeypatch):
    _asignacion_falsa(monkeypatch)
    job = _job()
    workspace = ruta_workspace(job.id)
    resultados = workspace / "resultados"
    resultados.mkdir(parents=True, exist_ok=True)
    (resultados / "no_publicados_seisan.csv").write_text(
        "Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista\n"
        "2026-10-01 00:00:00,-30.0,-71.0,30.0,3.0,ML,ana\n",
        encoding="utf-8",
    )
    (resultados / "no_publicados_seiscomp.csv").write_text(
        "Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista\n"
        "2026-10-02 00:00:00,-31.0,-71.5,20.0,3.5,ML,beto\n",
        encoding="utf-8",
    )
    login()

    html = client.get(
        f"/jobs/{job.id}/paneles",
        query_string={"dataset": "observaciones", "fuente": "seisan"},
    ).get_data(as_text=True)

    assert "Filtro:" in html
    assert "Todos los tipos" in html
    assert "Seisan" in html
    assert "(1 evento)" in html
    assert "fuente=eventquery" not in html
    assert '<span class="btn btn-sm btn-outline-secondary disabled"' not in html


def test_territorio_evento_usa_clasificacion_precisa(monkeypatch):
    clasificaciones = {
        (-33.0, -71.0): {"pais": "Chile"},
        (-16.0, -71.0): {"pais": "Chile"},
        (-27.0, -109.0): {"pais": "Chile"},
        (-33.6, -78.8): {"pais": "Chile"},
        (-42.5, -74.0): {"pais": "Chile"},
        (7.0, -80.0): {"pais": "Panamá"},
        (-60.0, -60.0): {"pais": ""},
        (-0.8, -20.7): {"pais": ""},
        (-40.0, -100.0): {"pais": ""},
    }
    monkeypatch.setattr(
        panels.ubicacion,
        "clasificar",
        lambda lat, lon: clasificaciones.get((lat, lon)),
    )

    assert panels._territorio_evento(-33.0, -71.0) == "Nacional"
    assert panels._territorio_evento(-16.0, -71.0) == "Nacional"
    assert panels._territorio_evento(-27.0, -109.0) == "Insular"
    assert panels._territorio_evento(-33.6, -78.8) == "Insular"
    assert panels._territorio_evento(-42.5, -74.0) == "Nacional"
    assert panels._territorio_evento(7.0, -80.0) == "Otros"
    assert panels._territorio_evento(-60.0, -60.0) == "Antártico"
    assert panels._territorio_evento(-0.8, -20.7) == "Otros"
    assert panels._territorio_evento(-40.0, -100.0) == "Otros"


def test_territorio_evento_respaldo_sin_geometrias(monkeypatch):
    monkeypatch.setattr(panels.ubicacion, "clasificar", lambda lat, lon: None)

    assert panels._territorio_evento(-33.0, -71.0) == "Nacional"
    assert panels._territorio_evento(-33.6, -78.8) == "Insular"
    assert panels._territorio_evento(-60.0, -60.0) == "Antártico"
    assert panels._territorio_evento(7.0, -80.0) == "Otros"


def test_panel_evento_de_otro_pais_va_a_otros(app, monkeypatch):
    _asignacion_falsa(monkeypatch)
    monkeypatch.setattr(
        panels.ubicacion,
        "clasificar",
        lambda lat, lon: {"pais": "Perú"} if (lat, lon) == (-40.0, -100.0) else None,
    )
    job = _job()
    workspace = ruta_workspace(job.id)
    resultados = workspace / "resultados"
    resultados.mkdir(parents=True, exist_ok=True)
    (resultados / "no_publicados_seisan.csv").write_text(
        "Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista\n"
        "2026-10-01 00:00:00,-40.0,-100.0,30.0,3.0,ML,ana\n",
        encoding="utf-8",
    )

    datos = panels.cargar(workspace, "observaciones")

    assert [t["nombre"] for t in datos["territorios"]] == ["Otros"]
    assert datos["eventos"][0]["territorio"] == "Otros"


def test_panel_catalogo_eventquery_incluye_analista_probable(app, monkeypatch):
    _asignacion_falsa(monkeypatch)
    job = _job()
    workspace = ruta_workspace(job.id)
    datos_dir = workspace / "datos"
    datos_dir.mkdir(parents=True, exist_ok=True)
    (datos_dir / "new_2_eventquery.csv").write_text(
        ",Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Referencia,Percep.\n"
        "0,2026-10-03 15:53:56,-30.0,-71.0,30.0,2.8,ML,Coquimbo,S\n",
        encoding="utf-8",
    )
    (datos_dir / "atribucion_seisan.csv").write_text(
        "fecha_eventquery,lat_eventquery,lon_eventquery,analista,dt_seg,fuente\n"
        "2026-10-03 15:53:56,-30.0,-71.0,beto,0.0,seisan\n",
        encoding="utf-8",
    )
    (datos_dir / "atribucion_seiscomp.csv").write_text(
        "fecha_eventquery,lat_eventquery,lon_eventquery,analista,dt_seg,fuente\n"
        "2026-10-03 15:53:56,-30.0,-71.0,cris,0.0,seiscomp\n",
        encoding="utf-8",
    )
    resultados = workspace / "resultados"
    resultados.mkdir(parents=True, exist_ok=True)
    (resultados / "indice.json").write_text(
        json.dumps(
            {
                "catalogos": {
                    "eventquery": {
                        "archivo": "datos/new_2_eventquery.csv",
                        "filas": 1,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    datos = panels.cargar(workspace, "catalogo_eventquery")

    assert datos["eventos"][0]["analista"] == "SeisComp: cris; Seisan: beto"


def test_perfiles_grafico_incluye_la_linea_del_perfil(monkeypatch):
    monkeypatch.setattr(plots, "_perfiles", lambda: [_perfil_sintetico()])

    datos = panels.perfiles_grafico(["P001"])

    assert datos["P001"]["slab_lon"] == [-71, -71.5, -72]
    assert datos["P001"]["slab_lat"] == [-30, -30.5, -31]


def test_ruta_paneles_historico_devuelve_json(client, login, monkeypatch):
    job = _job()
    login()
    monkeypatch.setattr(
        panels,
        "perfil_historico",
        lambda perfil_id: {"id": perfil_id, "slab_p": [1.0]},
    )
    monkeypatch.setattr(
        "app.blueprints.panels.historico_datos",
        lambda _perfil: {
            "label": "Sismicidad histórica de prueba",
            "perfil": {"along": [1.0], "prof": [-2.0], "total": 1},
        },
    )

    respuesta = client.get(f"/jobs/{job.id}/paneles/historico/P001")

    assert respuesta.status_code == 200
    datos = respuesta.get_json()
    assert datos["label"] == "Sismicidad histórica de prueba"
    assert datos["perfil"]["total"] == 1


def test_ruta_paneles_historico_perfil_inexistente(client, login, monkeypatch):
    job = _job()
    login()
    monkeypatch.setattr(panels, "perfil_historico", lambda _perfil_id: None)

    respuesta = client.get(f"/jobs/{job.id}/paneles/historico/P999")

    assert respuesta.status_code == 404


def test_perfil_historico_usa_series_del_perfil(monkeypatch):
    monkeypatch.setattr(plots, "_perfiles", lambda: [_perfil_sintetico()])

    perfil = panels.perfil_historico("P001")

    assert perfil is not None
    assert perfil["id"] == "P001"
    assert perfil["slab_lon"] == [-71, -71.5, -72]
    assert perfil["slab_lat"] == [-30, -30.5, -31]


def test_ruta_paneles_eventquery_no_es_fuente_de_observaciones(client, login, monkeypatch):
    """Eventquery es referencia y no se ofrece como fuente de Observaciones."""
    _asignacion_falsa(monkeypatch)
    job = _job()
    workspace = ruta_workspace(job.id)
    resultados = workspace / "resultados"
    resultados.mkdir(parents=True, exist_ok=True)
    (resultados / "no_publicados_seisan.csv").write_text(
        "Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista\n"
        "2026-10-01 00:00:00,-30.0,-71.0,30.0,3.0,ML,ana\n",
        encoding="utf-8",
    )
    login()

    html = client.get(
        f"/jobs/{job.id}/paneles",
        query_string={"dataset": "observaciones", "fuente": "eventquery"},
    ).get_data(as_text=True)

    assert "fuente=eventquery" not in html
    assert "Todas las fuentes" in html
    assert "(1 evento)" in html
    assert 'data-scroll="0"' in html

def test_ruta_paneles_tipo_sin_eventos_es_clickeable(client, login, monkeypatch):
    """Los tipos con 0 eventos también mantienen su enlace."""
    _asignacion_falsa(monkeypatch)
    job = _job()
    workspace = ruta_workspace(job.id)
    resultados = workspace / "resultados"
    resultados.mkdir(parents=True, exist_ok=True)
    (resultados / "no_publicados_seisan.csv").write_text(
        "Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista\n"
        "2026-10-01 00:00:00,-30.0,-71.0,30.0,3.0,ML,ana\n",
        encoding="utf-8",
    )
    login()

    html = client.get(
        f"/jobs/{job.id}/paneles",
        query_string={"dataset": "observaciones", "tipo": "repetido"},
    ).get_data(as_text=True)

    assert "tipo=repetido" in html
    assert "No hay eventos para" in html
    assert '<span class="btn btn-sm btn-outline-secondary disabled"' not in html


def _panel_con_perfil_y_territorio(monkeypatch):
    _asignacion_falsa(monkeypatch)
    job = _job()
    workspace = ruta_workspace(job.id)
    resultados = workspace / "resultados"
    resultados.mkdir(parents=True, exist_ok=True)
    (resultados / "no_publicados_seisan.csv").write_text(
        "Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista\n"
        "2026-10-01 00:00:00,-30.0,-71.0,30.0,3.0,ML,ana\n"
        "2026-10-02 00:00:00,-40.0,-100.0,20.0,3.5,ML,beto\n",
        encoding="utf-8",
    )
    return job


def test_grupo_eventos_distingue_perfil_y_territorio():
    eventos = [
        {
            "id": "p1",
            "perfil": "P001",
            "territorio": None,
            "lat": -30.0,
            "lon": -71.0,
            "along_km": 50.0,
            "tipo_observacion": "no_publicado",
            "sospechoso": False,
            "revision": "",
        },
        {
            "id": "t1",
            "perfil": None,
            "territorio": "Otros",
            "lat": -40.0,
            "lon": -100.0,
            "along_km": None,
            "tipo_observacion": "no_publicado",
            "sospechoso": True,
            "revision": "",
        },
    ]
    datos = {"eventos": eventos}

    perfil = panels.grupo_eventos(datos, "perfil", "P001")
    territorio = panels.grupo_eventos(datos, "territorio", "Otros")

    assert perfil["titulo"] == "Perfil P001"
    assert [evento["id"] for evento in perfil["eventos"]] == ["p1"]
    assert territorio["titulo"] == "Territorio Otros"
    assert [evento["id"] for evento in territorio["eventos"]] == ["t1"]
    assert panels.grupo_eventos(datos, "perfil", "P999") is None
    assert panels.grupo_eventos(datos, "otro", "P001") is None


def test_resumen_grupo_png_identifica_fuente_filtros_y_conteos():
    detalle = {
        "titulo": "Perfil P001",
        "eventos": [{"id": "p1"}],
        "resumen": {
            "no_publicados": 3,
            "no_actualizados": 2,
            "repetidos": 1,
            "sospechosos": 4,
        },
    }
    resumen = panels.resumen_grupo_png(
        detalle,
        dataset="observaciones",
        dataset_titulo="Resultados",
        tipo_titulo="No publicados",
        fuente_titulo="Seisan",
        job_id="job1",
    )

    assert resumen["filas"] == []
    assert resumen["titulo"] == "Perfil P001 · 1 evento"
    assert "Resultados · Fuente: Seisan · Tipo: No publicados" in resumen["subtitulo"]
    assert (
        "No publicados: 3 | No actualizados: 2 | Repetidos: 1 | "
        "Sospechosos: 4"
    ) in resumen["subtitulo"]
    assert "job1" in resumen["pie"]


def test_resumen_grupo_png_catalogo_no_muestra_conteos_por_tipo():
    detalle = {
        "titulo": "Perfil P002",
        "eventos": [{"id": "c1"}, {"id": "c2"}],
        "resumen": {"sospechosos": 0},
    }
    resumen = panels.resumen_grupo_png(
        detalle,
        dataset="catalogo_seiscomp",
        dataset_titulo="Catálogo SeisComp",
        tipo_titulo="Todos los tipos",
        fuente_titulo="SeisComp",
        job_id="job2",
    )

    assert resumen["filas"] == []
    assert resumen["subtitulo"] == ["Catálogo SeisComp · Fuente: SeisComp"]
    assert not any("No publicados" in linea for linea in resumen["subtitulo"])


def test_indice_paneles_agrega_columna_ver(client, login, monkeypatch):
    job = _panel_con_perfil_y_territorio(monkeypatch)
    login()

    html = client.get(
        f"/jobs/{job.id}/paneles",
        query_string={
            "dataset": "observaciones",
            "tipo": "no_publicado",
            "fuente": "seisan",
        },
    ).get_data(as_text=True)

    assert ">Ver</a>" in html
    assert "data-ver-grupo" in html
    assert f"/jobs/{job.id}/paneles/observaciones/perfil/P001" in html
    assert f"/jobs/{job.id}/paneles/observaciones/territorio/Otros" in html
    assert "tipo=no_publicado" in html
    assert "fuente=seisan" in html


def test_indice_paneles_preselecciona_grupo(client, login, monkeypatch):
    job = _panel_con_perfil_y_territorio(monkeypatch)
    login()

    html = client.get(
        f"/jobs/{job.id}/paneles",
        query_string={
            "dataset": "observaciones",
            "grupo": "perfil",
            "ident": "P001",
        },
    ).get_data(as_text=True)

    assert 'data-grupo-inicial="perfil"' in html
    assert 'data-ident-inicial="P001"' in html


def test_indice_paneles_ignora_grupo_inexistente(client, login, monkeypatch):
    job = _panel_con_perfil_y_territorio(monkeypatch)
    login()

    html = client.get(
        f"/jobs/{job.id}/paneles",
        query_string={
            "dataset": "observaciones",
            "grupo": "perfil",
            "ident": "P999",
        },
    ).get_data(as_text=True)

    assert 'data-grupo-inicial=""' in html
    assert 'data-ident-inicial=""' in html


def test_ruta_detalle_grupo_perfil(client, login, monkeypatch):
    job = _panel_con_perfil_y_territorio(monkeypatch)
    login()

    respuesta = client.get(
        f"/jobs/{job.id}/paneles/observaciones/perfil/P001"
    )

    assert respuesta.status_code == 200
    html = respuesta.get_data(as_text=True)
    assert "Perfil P001" in html
    assert "Descargar PNG" in html
    assert 'id="mapa-datos"' in html
    assert 'id="mapa-detalle"' in html
    assert 'id="perfil-detalle"' in html
    assert "mapa_detalle.js" in html
    assert "regiones_mapa.js" in html
    assert 'id="detalle-evento-panel"' in html
    assert 'id="detalle-evento-contenido"' in html
    assert "data-url-regiones" in html
    assert "paneles.js" not in html
    assert 'id="grupo-descargar-csv"' in html
    assert "grupo=perfil" in html
    assert "ident=P001" in html
    assert 'id="controles-estaciones-mapa"' not in html


def test_ruta_detalle_grupo_territorio_sin_perfil(client, login, monkeypatch):
    job = _panel_con_perfil_y_territorio(monkeypatch)
    login()

    respuesta = client.get(
        f"/jobs/{job.id}/paneles/observaciones/territorio/Otros"
    )

    assert respuesta.status_code == 200
    html = respuesta.get_data(as_text=True)
    assert "Territorio Otros" in html
    assert 'id="mapa-detalle"' in html
    assert "Sin perfil asignado" in html
    assert "Perfil no disponible" in html
    assert "mapa_detalle.js" in html
    assert 'id="detalle-evento-panel"' in html
    assert "paneles.js" not in html
    assert "grupo=territorio" in html
    assert "ident=Otros" in html
    assert 'id="controles-estaciones-mapa"' not in html


def test_ruta_detalle_grupo_inexistente(client, login, monkeypatch):
    job = _panel_con_perfil_y_territorio(monkeypatch)
    login()

    assert (
        client.get(
            f"/jobs/{job.id}/paneles/observaciones/perfil/P999"
        ).status_code
        == 404
    )


def test_ruta_png_grupo_no_incluye_filas_de_eventos(client, login, monkeypatch):
    job = _panel_con_perfil_y_territorio(monkeypatch)
    login()
    capturado = {}

    def falso(workspace, eventos, fuente, resumen, cache_key, modo="auto"):
        capturado.update(
            {
                "eventos": eventos,
                "fuente": fuente,
                "resumen": resumen,
                "cache_key": cache_key,
                "modo": modo,
            }
        )
        return b"\x89PNG\r\n\x1a\n" + b"0" * 32

    monkeypatch.setattr(plots, "generar_mapa_grupo", falso)

    respuesta = client.get(
        f"/jobs/{job.id}/paneles/observaciones/perfil/P001/mapa.png",
        query_string={"tipo": "no_publicado", "fuente": "seisan"},
    )

    assert respuesta.status_code == 200
    assert respuesta.mimetype == "image/png"
    assert capturado["modo"] == "auto"
    assert capturado["resumen"]["filas"] == []
    assert "Fuente: Seisan" in capturado["resumen"]["subtitulo"][0]
    assert "Tipo: No publicados" in capturado["resumen"]["subtitulo"][0]
    assert "No publicados: 1" in capturado["resumen"]["subtitulo"][1]
    assert capturado["eventos"][0]["latitud"] == -30.0
    assert "no_publicado" in capturado["cache_key"]


def test_ruta_png_grupo_territorio_fuerza_planta(client, login, monkeypatch):
    job = _panel_con_perfil_y_territorio(monkeypatch)
    login()
    capturado = {}

    def falso(workspace, eventos, fuente, resumen, cache_key, modo="auto"):
        capturado["modo"] = modo
        return b"\x89PNG\r\n\x1a\n" + b"0" * 32

    monkeypatch.setattr(plots, "generar_mapa_grupo", falso)

    respuesta = client.get(
        f"/jobs/{job.id}/paneles/observaciones/territorio/Otros/mapa.png"
    )

    assert respuesta.status_code == 200
    assert capturado["modo"] == "planta"


def test_ruta_detalle_grupo_respeta_mapa_offline(client, login, monkeypatch):
    job = _panel_con_perfil_y_territorio(monkeypatch)
    login()

    html = client.get(
        f"/jobs/{job.id}/paneles/observaciones/perfil/P001",
        query_string={"mapa": "offline"},
    ).get_data(as_text=True)

    assert 'data-modo="offline"' in html
    assert 'id="mapa-datos"' in html
    assert 'id="perfil-datos"' in html
    assert "mapa_detalle.js" in html
