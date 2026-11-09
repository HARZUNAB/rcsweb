"""Revisión de estaciones: contrato canónico, servicio y rutas de detalle."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from app.domain.catalogs.canonical import (
    escribir_desde_csv,
    escribir_extensiones,
    leer_meta,
)
from app.extensions import db
from app.models import Job, nuevo_uuid
from app.services import amplification, availability
from app.services.results import leer_csv
from app.services.station_review import (
    _fila_sin_arribos,
    filas_para_csv,
    filas_visibles,
    revisar_evento,
    revisar_fila,
    seleccionar_disponibilidad,
)
from app.services.workspace import crear_workspace

RAW = (
    "id_evento,id_origen,ot_utc,magnitud,tipo_magnitud,fases,rms,azgap,"
    "latitud,longitud,profundidad_km,agencia,operador,region,estatus,base_datos\n"
    "csn_test_0001,Origin/20261003155356.000,2026-10-03 15:53:56,2.8,ML,"
    "12,0.30,40,-29.519,-72.594,30.0,SNC,beto,Coquimbo,confirmed,seiscomp\n"
)

NORMALIZADO = (
    ",Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista\n"
    "0,2026-10-03  15:53:56,-29.519,-72.594,30.0,2.8,ML,beto\n"
)

FASES = (
    "id_evento,id_origen,id_pick,red,estacion,loc,cha,fase,llegada_utc,"
    "llegada_us,correccion_s,residual_s,azimut,distancia,usada,peso,polaridad,"
    "modo_pick,pick_autor,pick_agencia,pick_metodo,snr,mag_estacion,"
    "tipo_mag_estacion,tiene_magnitud,mag_est_residuo,qc_estacion,est_lat,"
    "est_lon,est_elev,est_lugar,est_pais,base_datos\n"
    "csn_test_0001,Origin/20261003155356.000,pick-1,IU,ANMO,00,BHZ,P,"
    "2026-10-03 15:54:20,123000,0.10,0.50,45.0,3.2,Si,0.8,,manual,jperez,"
    "SNC,,12.5,1.2,ML,Si,0.3,aprobado,-29.1,-71.1,1200,Coquimbo,Chile,"
    "seiscomp\n"
    "csn_test_0001,Origin/20261003155356.000,pick-2,CI,ML02,00,HHZ,P,"
    "2026-10-03 15:54:25,,,,,,No,0.0,,automatic,scautopick,SNC,AIC,,,,"
    ",,,,-30.2,-71.4,800,La Serena,Chile,seiscomp\n"
)

SIN_ARRIBOS = (
    "id_evento,id_origen,red,estacion,loc_ref,cha_ref,streams_vigentes,"
    "streams_vigentes_ids,distancia_km,est_lat,est_lon,est_elev,est_lugar,"
    "est_pais,radio_km,actividad_ventana,evidencia,waveform_status,"
    "availability_source,cobertura_desde,cobertura_hasta\n"
    "csn_test_0001,Origin/20261003155356.000,IU,LVC,00,BHZ,"
    "IU.LVC.00.BHZ;IU.LVC.00.HHZ,IU.LVC.00.BHZ;IU.LVC.00.HHZ,12.3,"
    "-29.1,-71.1,1200,Coquimbo,Chile,400,2,INDICIO,NO_CONSULTADO,,,\n"
)

FILA_BASE_AMPLIADA = {
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

FILA_BASE_AMPLIADA_2 = dict(
    FILA_BASE_AMPLIADA,
    estacion="LVC2",
    streams_vigentes=1,
    streams_vigentes_ids="IU.LVC2.00.BHZ",
    distancia_km=200.0,
)


def _poblar(workspace, *, extensiones: bool = True, con_sin_arribos: bool = True):
    (workspace / "datos").mkdir(parents=True, exist_ok=True)
    (workspace / "files").mkdir(parents=True, exist_ok=True)
    raw = workspace / "files" / "seiscomp_20261001000000_20261031235959.csv"
    raw.write_text(RAW, encoding="utf-8")
    normalizado = workspace / "datos" / "seiscomp_parametros.csv"
    normalizado.write_text(NORMALIZADO, encoding="utf-8")
    escribir_desde_csv(
        workspace,
        "seiscomp",
        "seiscomp",
        normalizado,
        ruta_cruda=raw,
    )
    if not extensiones:
        return workspace

    fases = workspace / "files" / "seiscomp_20261001000000_20261031235959_fases.csv"
    fases.write_text(FASES, encoding="utf-8")
    sin_arribos = (
        workspace / "files" / "seiscomp_20261001000000_20261031235959_no_picadas.csv"
    )
    if con_sin_arribos:
        sin_arribos.write_text(SIN_ARRIBOS, encoding="utf-8")
    escribir_extensiones(
        workspace,
        "seiscomp",
        "seiscomp",
        {
            "arribos": "files/seiscomp_20261001000000_20261031235959_fases.csv",
            "estaciones_sin_arribos": (
                "files/seiscomp_20261001000000_20261031235959_no_picadas.csv"
                if con_sin_arribos
                else None
            ),
        },
    )
    return workspace


def _workspace(tmp_path, *, extensiones: bool = True):
    return _poblar(tmp_path / "ws", extensiones=extensiones)


def test_canonico_enlaza_id_evento_y_escribe_meta(tmp_path):
    workspace = _workspace(tmp_path)

    from app.domain.catalogs.canonical import (
        leer_arribos,
        leer_canonico,
        leer_estaciones_sin_arribos,
    )

    evento = leer_canonico(workspace, "seiscomp")[0]
    assert evento["source_event_id"] == "csn_test_0001"
    assert evento["origin_id"] == "Origin/20261003155356.000"
    assert evento["database"] == "seiscomp"
    assert evento["raw_index"] == 0

    arribos = leer_arribos(workspace, "seiscomp")
    assert len(arribos) == 2
    assert [fila["event_id"] for fila in arribos] == ["seiscomp:000000"] * 2

    estaciones = leer_estaciones_sin_arribos(workspace, "seiscomp")
    assert estaciones[0]["streams"] == "IU.LVC.00.BHZ;IU.LVC.00.HHZ"
    assert estaciones[0]["stream_ids"] == "IU.LVC.00.BHZ;IU.LVC.00.HHZ"

    meta = leer_meta(workspace, "seiscomp")
    assert meta["schema_version"] == "1.1"
    assert meta["extensions"]["arribos"]["rows"] == 2
    assert meta["extensions"]["estaciones_sin_arribos"]["rows"] == 1
    assert meta["station_radius_km"] == 400.0


def test_revision_agrupa_y_filtra_no_utilizadas(tmp_path):
    workspace = _workspace(tmp_path)
    evento = {
        "event_id": "seiscomp:000000",
        "source_event_id": "csn_test_0001",
        "event_time": "2026-10-03 15:53:56",
        "latitude": -29.519,
        "longitude": -72.594,
    }

    revision = revisar_evento(workspace, "seiscomp", evento)

    assert revision["estado"] == "ok"
    assert revision["motivo"] == ""
    assert revision["resumen"]["arribos"] == 2
    assert revision["resumen"]["usadas"] == 1
    assert revision["resumen"]["no_usadas"] == 1
    assert revision["resumen"]["radio_km"] == 400.0
    assert [grupo["etiqueta"] for grupo in revision["grupos"]] == [
        "IU ANMO",
        "CI ML02",
    ]
    assert len(revision["sin_arribos"]) == 1
    assert revision["resumen"]["sin_arribos"] == 1

    anmo = revision["grupos"][0]["filas"][0]
    ml02 = revision["grupos"][1]["filas"][0]
    assert anmo["modo"] == "Manual"
    assert anmo["qc"] == "Aprobado"
    assert anmo["usada"] == "Sí"
    assert anmo["_clase"] == "pick-manual-usada"
    assert ml02["modo"] == "Automático"
    assert ml02["qc"] == ""
    assert ml02["usada"] == "No"
    assert ml02["_clase"] == ""

    assert revision["radio_exportado"] == 400.0
    assert revision["radio_mostrar"] == 400.0
    assert revision["cerca_km"] == 50.0
    assert revision["mostradas"] == 1
    assert revision["resaltadas"] == 1
    assert "Mostrando 1 de 1" in revision["texto_estado"]
    assert revision["max_estaciones"] == 150
    assert revision["max_streams"] == 5000
    assert revision["consulta_estaciones"] == 1
    assert revision["consulta_total"] == 1
    assert revision["consulta_omitidas"] == 0
    assert revision["consulta_pendientes"] == 1
    assert revision["consulta_requiere_todas"] is False
    assert revision["sin_arribos"][0]["_categoria"] == "indicio"

    assert revision["tiene_coordenadas"] is True
    assert revision["tiene_estimadas"] is True
    assert revision["tiene_tiempos"] is True
    mapa = revision["estaciones_mapa"]
    assert len(mapa) == 2
    por_estacion = {punto["estacion"]: punto for punto in mapa}
    assert set(por_estacion) == {"ANMO", "LVC"}
    assert por_estacion["ANMO"]["tipo"] == "arribo"
    assert por_estacion["ANMO"]["fase"] == "P"
    assert len(por_estacion["ANMO"]["fases"]) == 1
    assert por_estacion["LVC"]["tipo"] == "sin_arribo"
    assert por_estacion["LVC"]["lat"] == -29.1
    assert por_estacion["LVC"]["lon"] == -71.1
    assert por_estacion["LVC"]["categoria"] == "indicio"

    tiempos = revision["tiempos_llegada"]
    assert tiempos["event_time"] == "2026-10-03 15:53:56"
    assert tiempos["evento"]["lat"] == -29.519
    assert tiempos["evento"]["lon"] == -72.594
    arribos_tiempo = {fila["estacion"]: fila for fila in tiempos["arribos"]}
    assert set(arribos_tiempo) == {"ANMO", "ML02"}
    assert arribos_tiempo["ANMO"]["segundos"] == 24.123
    assert arribos_tiempo["ML02"]["segundos"] == 29.0
    assert arribos_tiempo["ANMO"]["distancia_km"] > 100
    assert [fila["estacion"] for fila in tiempos["estaciones"]] == ["LVC"]

    columnas_sin, filas_sin = filas_para_csv(revision, "sin_arribos")
    assert "Streams vigentes" in columnas_sin
    indice_streams = columnas_sin.index("Streams vigentes")
    assert filas_sin[0][indice_streams] == "IU.LVC.00.BHZ;IU.LVC.00.HHZ"
    assert ("stream_ref", "Streams") in revision["columnas_sin_arribos"]
    assert ("disponible", "Disp. no usada") in revision[
        "columnas_sin_arribos"
    ]

    filtrada = revisar_evento(
        workspace, "seiscomp", evento, solo_no_usadas=True
    )
    assert filtrada["resumen"]["arribos"] == 1
    assert [grupo["etiqueta"] for grupo in filtrada["grupos"]] == ["CI ML02"]

    columnas, filas = filas_para_csv(filtrada, "arribos")
    assert columnas[:2] == ["Red", "Estación"]
    assert len(filas) == 1
    assert filas[0][:2] == ["CI", "ML02"]
    assert "No" in filas[0]


def test_revision_solo_arribos_alimenta_mapa_y_tiempos(tmp_path):
    workspace = _poblar(tmp_path / "ws", con_sin_arribos=False)
    evento = {
        "event_id": "seiscomp:000000",
        "source_event_id": "csn_test_0001",
        "event_time": "2026-10-03 15:53:56",
        "latitude": -29.519,
        "longitude": -72.594,
    }

    revision = revisar_evento(workspace, "seiscomp", evento)

    assert revision["estado"] == "ok"
    assert revision["sin_arribos"] == []
    assert revision["tiene_coordenadas"] is True
    assert revision["tiene_estimadas"] is False
    assert revision["tiene_tiempos"] is True
    mapa = revision["estaciones_mapa"]
    assert {punto["estacion"] for punto in mapa} == {"ANMO"}
    assert all(punto["tipo"] == "arribo" for punto in mapa)
    assert revision["tiempos_llegada"]["estaciones"] == []
    assert len(revision["tiempos_llegada"]["arribos"]) == 2


def test_revision_no_evaluable_si_falta_el_archivo(tmp_path):
    workspace = _workspace(tmp_path, extensiones=False)
    evento = {
        "event_id": "seiscomp:000000",
        "source_event_id": "csn_test_0001",
    }

    revision = revisar_evento(workspace, "seiscomp", evento)

    assert revision["estado"] == "no_evaluable"
    assert revision["motivo"] == (
        "Este trabajo no incluye la revisión de estaciones."
    )
    assert revision["grupos"] == []


def test_revision_resuelve_por_tiempo_y_posicion(tmp_path):
    workspace = _workspace(tmp_path)
    fila = {
        "Fecha_Hora": "2026-10-03 15:53:56",
        "Latitud": "-29.519",
        "Longitud": "-72.594",
    }

    revision = revisar_fila(workspace, "no_publicados", "seiscomp", fila)

    assert revision["estado"] == "ok"
    assert revision["resumen"]["arribos"] == 2


def test_leer_csv_conserva_indice_crudo(tmp_path):
    ruta = tmp_path / "datos.csv"
    ruta.write_text(
        ",Fecha_Hora,Latitud\n0,2026-10-03 15:53:56,-29.5\n",
        encoding="utf-8",
    )

    columnas, filas = leer_csv(ruta)

    assert columnas == ["Fecha_Hora", "Latitud"]
    assert filas[0]["_indice_crudo"] == 0


def test_preparar_entradas_copia_extensiones(app):
    from app.models import JobFile, JobSource
    from app.services.workspace import preparar_entradas, ruta_workspace

    job = _job(app)
    nombre = "seiscomp_20261001000000_20261031235959"
    workspace = ruta_workspace(job.id)
    (workspace / "inputs").mkdir(parents=True, exist_ok=True)
    (workspace / "files").mkdir(parents=True, exist_ok=True)
    (workspace / "inputs" / f"seiscomp__{nombre}.csv").write_text(
        RAW, encoding="utf-8"
    )
    (workspace / "files" / f"{nombre}_fases.csv").write_text(
        FASES, encoding="utf-8"
    )
    (workspace / "files" / f"{nombre}_no_picadas.csv").write_text(
        SIN_ARRIBOS, encoding="utf-8"
    )
    db.session.add(
        JobSource(
            job_id=job.id,
            kind="seiscomp",
            alias="SeisComp",
            format="seiscomp",
            role="local_principal",
            priority=1,
            capabilities=["eventos", "arribos", "inventario"],
        )
    )
    db.session.add(
        JobFile(
            job_id=job.id,
            kind="seiscomp",
            original_name=f"{nombre}.csv",
            stored_name=f"inputs/seiscomp__{nombre}.csv",
            size=1,
            sha256="x",
        )
    )
    db.session.commit()

    preparar_entradas(job)

    assert (workspace / f"{nombre}.csv").is_file()
    assert (workspace / f"{nombre}_fases.csv").is_file()
    assert (workspace / f"{nombre}_no_picadas.csv").is_file()


def _usuario(username, code, role="analista"):
    from app.models import User

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


def _job(app, creado_por=None):
    job = Job(
        id=nuevo_uuid(),
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 31, 23, 59, 59, tzinfo=UTC),
        status="done",
        created_by_id=creado_por,
    )
    db.session.add(job)
    db.session.commit()
    return job


def _job_con_revision(app, *, con_sin_arribos: bool = True):
    job = _job(app)
    workspace = _poblar(
        app.config["WORKSPACE_ROOT"] / job.id,
        con_sin_arribos=con_sin_arribos,
    )
    resultados = workspace / "resultados"
    resultados.mkdir(parents=True, exist_ok=True)
    (resultados / "no_publicados_seiscomp.csv").write_text(
        "Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista,"
        "Publicado_en,Estado,Dt_otra_seg,Dist_otra_km,Analista_otra\n"
        "2026-10-03 15:53:56,-29.519,-72.594,30.0,2.8,ML,beto,,"
        "Sin coincidencia,,,\n",
        encoding="utf-8",
    )
    (resultados / "indice.json").write_text(
        json.dumps(
            {
                "no_publicados": {
                    "seiscomp": {
                        "archivo": "no_publicados_seiscomp.csv",
                        "filas": 1,
                    }
                },
                "no_actualizados": {},
                "repetidos": {},
                "catalogos": {
                    "seiscomp": {
                        "archivo": "datos/seiscomp_parametros.csv",
                        "filas": 1,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return job


def test_detalle_muestra_revision_y_descarga(client, login, app):
    app.config["RCS_DISPONIBILIDAD_URL"] = "http://sidecar:8010"
    job = _job_con_revision(app)
    login()

    html = client.get(
        f"/jobs/{job.id}/resultados/no_publicados/seiscomp/0"
    ).get_data(as_text=True)

    assert "Revisión de estaciones" in html
    assert "Con arribos" in html
    assert "Sin arribos" in html
    assert "IU ANMO" in html
    assert "Solo no utilizadas" in html
    assert "Descargar arribos" in html
    assert "Qué significa cada columna" in html
    assert "Disp. no usada" in html
    assert "Ver todos" in html
    assert "modal-streams" in html
    assert 'data-streams="IU.LVC.00.BHZ;IU.LVC.00.HHZ"' in html
    assert "filtros-sin-arribos" in html
    assert "filtro-radio" in html
    assert "filtro-cerca" in html
    assert "filtro-solo" in html
    assert "Solo cercanas" in html
    assert "Colores (cerca" in html
    assert "no-picada-indicio" in html
    assert 'data-categoria="indicio"' in html
    assert "Colores de las llegadas" in html
    assert "pick-manual-usada" in html
    assert 'id="btn-estaciones-mapa"' in html
    assert 'id="btn-tiempos-llegada"' in html
    assert 'id="modal-tiempos"' in html
    assert 'id="estaciones-mapa-datos"' in html
    assert html.index('id="controles-estaciones-mapa"') < html.index(
        'id="mapa-detalle"'
    )
    assert html.count('id="btn-estaciones-mapa"') == 1
    assert html.count('id="btn-tiempos-llegada"') == 1
    assert html.count('id="modal-tiempos"') == 1
    assert 'id="btn-propagacion"' in html
    assert 'id="propagacion-controles"' in html
    assert 'id="propagacion-tiempo"' in html
    assert 'id="btn-propagacion-play"' in html
    assert 'id="btn-propagacion-consultar"' in html
    assert 'id="propagacion-estimadas"' in html
    assert 'id="propagacion-consulta-estado"' in html
    assert html.count('id="btn-propagacion"') == 1
    assert html.count('id="propagacion-controles"') == 1
    assert 'id="tiempos-llegada-datos"' in html

    respuesta = client.get(
        f"/jobs/{job.id}/resultados/no_publicados/seiscomp/0/estaciones/arribos.csv"
    )
    assert respuesta.status_code == 200
    texto = respuesta.get_data().decode("utf-8-sig")
    assert texto.splitlines()[0].startswith("Red,Estación,Fase")
    assert "ANMO" in texto

    sin_arribos = client.get(
        f"/jobs/{job.id}/resultados/no_publicados/seiscomp/0/estaciones/sin-arribos.csv"
    )
    assert sin_arribos.status_code == 200
    texto_sin = sin_arribos.get_data().decode("utf-8-sig")
    assert texto_sin.splitlines()[0].startswith("Dist. (km),Red,Estación")
    assert "Streams vigentes" in texto_sin.splitlines()[0]
    assert "IU.LVC.00.HHZ" in texto_sin
    assert "Indicio (actividad)" in texto_sin


def _json_embebido(html: str, id_elemento: str):
    patron = re.compile(
        r'<script type="application/json"\s+id="'
        + re.escape(id_elemento)
        + r'">(.*?)</script>',
        re.S,
    )
    coincidencia = patron.search(html)
    assert coincidencia is not None
    return json.loads(coincidencia.group(1))


def test_detalle_datos_mapa_y_tiempos(client, login, app):
    job = _job_con_revision(app)
    login()

    html = client.get(
        f"/jobs/{job.id}/resultados/no_publicados/seiscomp/0"
    ).get_data(as_text=True)

    estaciones = _json_embebido(html, "estaciones-mapa-datos")
    assert len(estaciones) == 2
    por_estacion = {punto["estacion"]: punto for punto in estaciones}
    assert set(por_estacion) == {"ANMO", "LVC"}
    assert por_estacion["LVC"]["tipo"] == "sin_arribo"
    assert por_estacion["LVC"]["lat"] == -29.1
    assert por_estacion["LVC"]["lon"] == -71.1
    assert por_estacion["LVC"]["distancia_km"] == 12.3
    assert por_estacion["LVC"]["categoria"] == "indicio"
    assert por_estacion["ANMO"]["tipo"] == "arribo"
    assert por_estacion["ANMO"]["fase"] == "P"
    assert por_estacion["ANMO"]["fases"][0]["modo"] == "Manual"

    tiempos = _json_embebido(html, "tiempos-llegada-datos")
    assert tiempos["event_time"] == "2026-10-03 15:53:56"
    assert tiempos["evento"] == {"lat": -29.519, "lon": -72.594}
    arribos = {fila["estacion"]: fila for fila in tiempos["arribos"]}
    assert set(arribos) == {"ANMO", "ML02"}
    assert arribos["ANMO"]["segundos"] == 24.123
    assert arribos["ANMO"]["distancia_km"] > 100
    assert [fila["estacion"] for fila in tiempos["estaciones"]] == ["LVC"]


def test_detalle_solo_arribos_muestra_controles(client, login, app):
    job = _job_con_revision(app, con_sin_arribos=False)
    login()

    html = client.get(
        f"/jobs/{job.id}/resultados/no_publicados/seiscomp/0"
    ).get_data(as_text=True)

    assert 'id="controles-estaciones-mapa"' in html
    assert html.index('id="controles-estaciones-mapa"') < html.index(
        'id="mapa-detalle"'
    )
    assert html.count('id="btn-estaciones-mapa"') == 1
    assert html.count('id="btn-tiempos-llegada"') == 1
    assert html.count('id="modal-tiempos"') == 1
    assert 'id="btn-propagacion"' in html
    assert 'id="propagacion-controles"' in html
    assert html.count('id="btn-propagacion"') == 1
    assert 'id="btn-propagacion-consultar"' not in html
    assert 'id="estaciones-mapa-datos"' in html
    assert 'id="tiempos-llegada-datos"' in html

    estaciones = _json_embebido(html, "estaciones-mapa-datos")
    assert {punto["estacion"] for punto in estaciones} == {"ANMO"}
    assert all(punto["tipo"] == "arribo" for punto in estaciones)

    tiempos = _json_embebido(html, "tiempos-llegada-datos")
    assert tiempos["estaciones"] == []
    assert len(tiempos["arribos"]) == 2


def test_descarga_respeta_visibilidad_del_analista(client, login, app):
    ana = _usuario("ana", "ana")
    _usuario("beto", "beto")
    job = _job(app, creado_por=ana.id)
    workspace = _poblar(app.config["WORKSPACE_ROOT"] / job.id)
    resultados = workspace / "resultados"
    resultados.mkdir(parents=True, exist_ok=True)
    (resultados / "no_publicados_seiscomp.csv").write_text(
        "Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista,"
        "Publicado_en,Estado,Dt_otra_seg,Dist_otra_km,Analista_otra\n"
        "2026-10-03 15:53:56,-29.519,-72.594,30.0,2.8,ML,ana,,"
        "Sin coincidencia,,,\n"
        "2026-10-03 16:00:00,-30.000,-71.000,20.0,3.1,ML,beto,,"
        "Sin coincidencia,,,\n",
        encoding="utf-8",
    )
    (resultados / "indice.json").write_text(
        json.dumps(
            {
                "no_publicados": {
                    "seiscomp": {
                        "archivo": "no_publicados_seiscomp.csv",
                        "filas": 2,
                    }
                },
                "no_actualizados": {},
                "repetidos": {},
                "catalogos": {},
            }
        ),
        encoding="utf-8",
    )
    client.post("/logout")
    client.post("/login", data={"username": "ana", "password": "secret"})

    propio = client.get(
        f"/jobs/{job.id}/resultados/no_publicados/seiscomp/0/estaciones/arribos.csv"
    )
    ajeno = client.get(
        f"/jobs/{job.id}/resultados/no_publicados/seiscomp/1/estaciones/arribos.csv"
    )

    assert propio.status_code == 200
    assert ajeno.status_code == 403


def test_detalle_muestra_no_evaluable_sin_archivos(client, login, app):
    job = _job(app)
    workspace = _poblar(
        app.config["WORKSPACE_ROOT"] / job.id, extensiones=False
    )
    resultados = workspace / "resultados"
    resultados.mkdir(parents=True, exist_ok=True)
    (resultados / "no_publicados_seiscomp.csv").write_text(
        "Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista,"
        "Publicado_en,Estado,Dt_otra_seg,Dist_otra_km,Analista_otra\n"
        "2026-10-03 15:53:56,-29.519,-72.594,30.0,2.8,ML,beto,,"
        "Sin coincidencia,,,\n",
        encoding="utf-8",
    )
    (resultados / "indice.json").write_text(
        json.dumps(
            {
                "no_publicados": {
                    "seiscomp": {
                        "archivo": "no_publicados_seiscomp.csv",
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
    login()

    html = client.get(
        f"/jobs/{job.id}/resultados/no_publicados/seiscomp/0"
    ).get_data(as_text=True)

    assert "Revisión de estaciones" in html
    assert "No evaluable:" in html
    assert "Este trabajo no incluye la revisión de estaciones." in html
    assert 'id="btn-estaciones-mapa"' not in html
    assert 'id="btn-tiempos-llegada"' not in html


def test_detalle_no_muestra_revision_sin_capacidad(
    client, login, app, monkeypatch
):
    job = _job(app)
    workspace = crear_workspace(job.id)
    resultados = workspace / "resultados"
    resultados.mkdir(parents=True, exist_ok=True)
    (resultados / "no_publicados_seiscomp.csv").write_text(
        "Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista,"
        "Publicado_en,Estado,Dt_otra_seg,Dist_otra_km,Analista_otra\n"
        "2026-10-03 15:53:56,-29.519,-72.594,30.0,2.8,ML,beto,,"
        "Sin coincidencia,,,\n",
        encoding="utf-8",
    )
    (resultados / "indice.json").write_text(
        json.dumps(
            {
                "no_publicados": {
                    "seiscomp": {
                        "archivo": "no_publicados_seiscomp.csv",
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
    # El manifiesto actual sí declara arribos: se simula una fuente sin esa
    # capacidad para comprobar que la sección no se muestra.
    login()
    import app.services.station_review as station_review

    monkeypatch.setattr(
        station_review.fuentes_manifest,
        "capacidades",
        lambda _codigo: frozenset({"eventos"}),
    )
    html = client.get(
        f"/jobs/{job.id}/resultados/no_publicados/seiscomp/0"
    ).get_data(as_text=True)

    assert "Revisión de estaciones" not in html


def test_fila_sin_arribos_con_datos_y_actividad(tmp_path):
    fila = _fila_sin_arribos(
        {
            "network": "AI",
            "station": "DSPA",
            "waveform_status": "SIN_DATOS",
            "activity_window": 3,
            "stream_ids": "AI.DSPA.02.BHZ",
        }
    )

    assert fila["formas_onda"] == "Sin datos"
    assert fila["evidencia"] == "Indicio (actividad)"
    assert fila["disponible"] == "No"
    assert fila["_estado_disponibilidad"] == "SIN_DATOS"
    assert fila["_streams"] == ["AI.DSPA.02.BHZ"]


def test_filtros_de_radio_y_cercania(tmp_path):
    workspace = _workspace(tmp_path)
    evento = {
        "event_id": "seiscomp:000000",
        "source_event_id": "csn_test_0001",
    }

    revision = revisar_evento(
        workspace,
        "seiscomp",
        evento,
        radio_km=10,
        cerca_km=5,
        solo_cercanas=False,
    )
    assert revision["radio_mostrar"] == 10.0
    assert revision["mostradas"] == 0
    assert revision["resaltadas"] == 0
    assert "Mostrando 0 de 1" in revision["texto_estado"]

    revision = revisar_evento(
        workspace,
        "seiscomp",
        evento,
        radio_km=20,
        cerca_km=20,
        solo_cercanas=False,
    )
    assert revision["mostradas"] == 1
    assert revision["resaltadas"] == 1

    revision = revisar_evento(
        workspace,
        "seiscomp",
        evento,
        radio_km=400,
        cerca_km=5,
        solo_cercanas=True,
    )
    assert revision["mostradas"] == 0
    assert "solo ≤ 5 km" in revision["texto_estado"]

    revision = revisar_evento(
        workspace, "seiscomp", evento, radio_km=1000, cerca_km=50
    )
    assert revision["radio_mostrar"] == 400.0
    assert revision["radio_limitado"] is True

    filas = revision["sin_arribos"]
    assert filas_visibles(filas, radio_km=10) == []
    assert len(filas_visibles(filas, radio_km=20)) == 1
    assert filas_visibles(filas, cerca_km=5, solo_cercanas=True) == []


def test_fila_sin_arribos_con_un_solo_stream():
    fila = _fila_sin_arribos(
        {
            "network": "IU",
            "station": "LVC",
            "waveform_status": "NO_CONSULTADO",
            "activity_window": 0,
            "stream_ids": "IU.LVC.00.BHZ",
        }
    )

    assert fila["stream_ref"] == "IU.LVC.00.BHZ"
    assert fila["streams_ids"] == "IU.LVC.00.BHZ"
    assert ";" not in fila["streams_ids"]


def test_seleccion_disponibilidad_prioriza_cercanas():
    filas = [
        {"estacion": "A", "_distancia": 100.0, "_streams": ["a1", "a2"]},
        {"estacion": "B", "_distancia": 10.0, "_streams": ["b1"]},
        {"estacion": "C", "_distancia": 50.0, "_streams": ["c1"]},
    ]

    seleccion, total, omitidas = seleccionar_disponibilidad(
        filas, max_estaciones=2, max_streams=100
    )
    assert [fila["estacion"] for fila in seleccion] == ["B", "C"]
    assert total == 3
    assert omitidas == 1

    todas, total, omitidas = seleccionar_disponibilidad(
        filas, todas=True, max_estaciones=1, max_streams=100
    )
    assert [fila["estacion"] for fila in todas] == ["B", "C", "A"]
    assert total == 3
    assert omitidas == 0

    filtradas, total, omitidas = seleccionar_disponibilidad(
        filas, radio_km=20, max_estaciones=10, max_streams=100
    )
    assert [fila["estacion"] for fila in filtradas] == ["B"]
    assert total == 1
    assert omitidas == 0

    limitadas, total, omitidas = seleccionar_disponibilidad(
        filas, todas=True, max_estaciones=10, max_streams=2
    )
    assert [fila["estacion"] for fila in limitadas] == ["B", "C"]
    assert total == 3
    assert omitidas == 1


def test_revision_ampliada(tmp_path):
    workspace = _workspace(tmp_path)
    evento = {
        "event_id": "seiscomp:000000",
        "source_event_id": "csn_test_0001",
    }
    amplification.guardar_ampliacion(
        workspace,
        "seiscomp",
        evento["event_id"],
        "sinlimite",
        [FILA_BASE_AMPLIADA],
    )

    revision = revisar_evento(
        workspace, "seiscomp", evento, ampliado="sinlimite"
    )

    assert revision["estado"] == "ok"
    assert revision["ampliado"] == "sinlimite"
    assert revision["ampliado_clave"] == "sinlimite"
    assert revision["radio_exportado"] is None
    assert len(revision["sin_arribos"]) == 1
    assert revision["sin_arribos"][0]["estacion"] == "LVC"
    assert revision["sin_arribos"][0]["distancia_km"] == "123.4"
    assert revision["aviso_sin_arribos"].startswith("Vista ampliada")
    assert "sin tope" in revision["texto_estado"]


def test_revision_superpone_cache_y_filtra_disponibles(tmp_path):
    workspace = _workspace(tmp_path)
    evento = {
        "event_id": "seiscomp:000000",
        "source_event_id": "csn_test_0001",
    }

    inicial = revisar_evento(workspace, "seiscomp", evento)
    fila = next(
        item for item in inicial["sin_arribos"] if item["estacion"] == "LVC"
    )
    availability.aplicar_a_filas(
        [fila],
        {
            "IU.LVC.00.BHZ": {
                "status": "CON_DATOS",
                "source": "SDS",
                "desde": "2026-10-03T15:44:00",
                "hasta": "2026-10-03T16:04:00",
            }
        },
    )
    availability.guardar_cache(
        workspace, "seiscomp", evento["event_id"], [fila]
    )

    revision = revisar_evento(workspace, "seiscomp", evento)
    actual = next(
        item for item in revision["sin_arribos"] if item["estacion"] == "LVC"
    )

    assert revision["disponibilidad_consultada"] is True
    assert revision["resumen"]["disponibles"] == 1
    assert revision["consulta_pendientes"] == 0
    assert actual["formas_onda"] == "SDS"
    assert actual["evidencia"] == "Verificado (SDS)"
    assert actual["_categoria"] == "verificado"
    assert actual["disponible"] == "Sí"
    assert actual["disponible_no_usada"] is True
    assert "2026-10-03" in actual["cobertura"]

    filtrada = revisar_evento(
        workspace, "seiscomp", evento, solo_disponibles=True
    )
    assert len(filtrada["sin_arribos"]) == 1
    assert filtrada["sin_arribos"][0]["estacion"] == "LVC"


def test_detalle_muestra_boton_disponibilidad_y_descarga(client, login, app):
    job = _job_con_revision(app)
    app.config["RCS_DISPONIBILIDAD_URL"] = "http://sidecar:8010"
    login()

    html = client.get(
        f"/jobs/{job.id}/resultados/no_publicados/seiscomp/0"
    ).get_data(as_text=True)

    assert "Consultar formas de onda" in html
    assert "estaciones.js" in html
    assert 'data-puede-consultar="1"' in html
    assert "data-url-encolar=" in html
    assert "data-url-estado=" in html
    assert "panel-sin-arribos-contenido" in html
    assert 'id="toasts"' in html
    assert re.search(
        r"<a[^>]*\bdownload\b[^>]*sin-arribos\.csv", html, re.S
    )
    assert re.search(r"<a[^>]*\bdownload\b[^>]*arribos\.csv", html, re.S)


def test_csv_sin_arribos_respeta_radio_y_cercania(client, login, app):
    job = _job_con_revision(app)
    login()
    base = (
        f"/jobs/{job.id}/resultados/no_publicados/seiscomp/0"
        "/estaciones/sin-arribos.csv"
    )

    incluido = client.get(base, query_string={"radio_km": 20})
    assert incluido.status_code == 200
    assert "IU.LVC.00.BHZ" in incluido.get_data().decode("utf-8-sig")

    fuera_radio = client.get(base, query_string={"radio_km": 5})
    assert fuera_radio.status_code == 404

    fuera_cerca = client.get(
        base, query_string={"solo_cercanas": "1", "cerca_km": 5}
    )
    assert fuera_cerca.status_code == 404


def test_detalle_ampliado_y_rutas(client, login, app, monkeypatch):
    from app.blueprints import results as results_bp

    job = _job_con_revision(app)
    app.config["RCS_DISPONIBILIDAD_URL"] = "http://sidecar:8010"
    workspace = app.config["WORKSPACE_ROOT"] / job.id
    amplification.guardar_ampliacion(
        workspace,
        "seiscomp",
        "seiscomp:000000",
        "sinlimite",
        [FILA_BASE_AMPLIADA],
    )
    login()

    html = client.get(
        f"/jobs/{job.id}/resultados/no_publicados/seiscomp/0",
        query_string={"ampliado": "sinlimite"},
    ).get_data(as_text=True)

    assert "Vista ampliada contra la base de SeisComp" in html
    assert "Volver a la lista exportada" in html
    assert "LVC" in html

    class Tarea:
        id = "task-amp"

    class TareaFalsa:
        @staticmethod
        def delay(*args, **kwargs):
            return Tarea()

    monkeypatch.setattr(results_bp, "ampliar_sin_arribos", TareaFalsa())
    monkeypatch.setattr(
        results_bp.amplification, "configurada", lambda: True
    )
    monkeypatch.setattr(
        results_bp.amplification, "tarea_en_curso", lambda *args, **kwargs: ""
    )
    monkeypatch.setattr(
        results_bp.amplification,
        "registrar_tarea",
        lambda *args, **kwargs: ("task-amp", True),
    )

    respuesta = client.post(
        f"/jobs/{job.id}/resultados/no_publicados/seiscomp/0"
        "/estaciones/ampliar",
        data={"sin_limite": "1"},
    )

    assert respuesta.status_code == 202
    assert respuesta.get_json()["clave"] == "sinlimite"

    class Resultado:
        state = "SUCCESS"
        result = {"estado": "ok", "clave": "sinlimite", "filas": 1}
        info = {}

    monkeypatch.setattr(
        results_bp.celery, "AsyncResult", lambda task_id: Resultado()
    )
    estado = client.get(
        f"/jobs/{job.id}/resultados/no_publicados/seiscomp/0"
        "/estaciones/ampliar/task-amp"
    )

    assert estado.status_code == 200
    datos = estado.get_json()
    assert datos["estado"] == "ok"
    assert datos["clave"] == "sinlimite"
    assert "ampliado=sinlimite" in datos["url"]


def test_detalle_ampliado_muestra_consultar_todas(
    client, login, app, monkeypatch
):
    job = _job_con_revision(app)
    app.config["RCS_DISPONIBILIDAD_URL"] = "http://sidecar:8010"
    workspace = app.config["WORKSPACE_ROOT"] / job.id
    amplification.guardar_ampliacion(
        workspace,
        "seiscomp",
        "seiscomp:000000",
        "sinlimite",
        [FILA_BASE_AMPLIADA, FILA_BASE_AMPLIADA_2],
    )
    monkeypatch.setattr(
        "app.services.availability.max_estaciones", lambda: 1
    )
    login()

    html = client.get(
        f"/jobs/{job.id}/resultados/no_publicados/seiscomp/0",
        query_string={"ampliado": "sinlimite"},
    ).get_data(as_text=True)

    assert "btn-disponibilidad-todas" in html
    assert "Consultar todas (2)" in html


def test_encolar_y_consultar_estado_disponibilidad(
    client, login, app, monkeypatch
):
    from app.blueprints import results as results_bp

    job = _job_con_revision(app)
    app.config["RCS_DISPONIBILIDAD_URL"] = "http://sidecar:8010"
    login()

    class Tarea:
        id = "task-1"

    class TareaFalsa:
        @staticmethod
        def delay(*args, **kwargs):
            return Tarea()

    monkeypatch.setattr(results_bp, "consultar_disponibilidad", TareaFalsa())
    monkeypatch.setattr(
        results_bp.availability, "tarea_en_curso", lambda *args, **kwargs: ""
    )
    monkeypatch.setattr(
        results_bp.availability,
        "registrar_tarea",
        lambda job_id, event_id, task_id, vista="": (task_id, True),
    )

    respuesta = client.post(
        f"/jobs/{job.id}/resultados/no_publicados/seiscomp/0"
        "/estaciones/disponibilidad"
    )

    assert respuesta.status_code == 202
    datos_encolado = respuesta.get_json()
    assert datos_encolado["task_id"] == "task-1"
    assert datos_encolado["total"] == 1
    assert datos_encolado["consultadas"] == 1
    assert datos_encolado["omitidas"] == 0

    class Resultado:
        state = "SUCCESS"
        result = {"estado": "ok", "estaciones": 1, "con_datos": 1}
        info = {}

    monkeypatch.setattr(
        results_bp.celery, "AsyncResult", lambda task_id: Resultado()
    )
    estado = client.get(
        f"/jobs/{job.id}/resultados/no_publicados/seiscomp/0"
        "/estaciones/disponibilidad/task-1"
    )

    assert estado.status_code == 200
    datos = estado.get_json()
    assert datos["estado"] == "ok"
    assert "Disp. no usada" in datos["html"]


def test_encolar_deduplica_tarea_en_curso(
    client, login, app, monkeypatch
):
    from app.blueprints import results as results_bp

    job = _job_con_revision(app)
    app.config["RCS_DISPONIBILIDAD_URL"] = "http://sidecar:8010"
    login()

    class TareaFalsa:
        @staticmethod
        def delay(*args, **kwargs):
            raise AssertionError("No se debía encolar otra tarea")

    monkeypatch.setattr(results_bp, "consultar_disponibilidad", TareaFalsa())
    monkeypatch.setattr(
        results_bp.availability,
        "tarea_en_curso",
        lambda *args, **kwargs: "task-previo",
    )

    respuesta = client.post(
        f"/jobs/{job.id}/resultados/no_publicados/seiscomp/0"
        "/estaciones/disponibilidad"
    )

    assert respuesta.status_code == 200
    assert respuesta.get_json()["task_id"] == "task-previo"


def test_detalle_retoma_tarea_en_curso(client, login, app, monkeypatch):
    from app.blueprints import results as results_bp

    job = _job_con_revision(app)
    app.config["RCS_DISPONIBILIDAD_URL"] = "http://sidecar:8010"
    monkeypatch.setattr(
        results_bp.availability,
        "tarea_en_curso",
        lambda *args, **kwargs: "task-en-curso",
    )
    login()

    html = client.get(
        f"/jobs/{job.id}/resultados/no_publicados/seiscomp/0"
    ).get_data(as_text=True)

    assert 'data-tarea="task-en-curso"' in html


def test_encolar_sin_servicio_configurado(client, login, app):
    job = _job_con_revision(app)
    app.config["RCS_DISPONIBILIDAD_URL"] = ""
    login()

    respuesta = client.post(
        f"/jobs/{job.id}/resultados/no_publicados/seiscomp/0"
        "/estaciones/disponibilidad"
    )

    assert respuesta.status_code == 503
    assert "no está disponible" in respuesta.get_json()["mensaje"]
