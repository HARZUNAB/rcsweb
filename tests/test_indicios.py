"""Pruebas de los indicios de anomalías en la identificación de fases."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from app.domain.catalogs import canonical
from app.extensions import db
from app.models import User
from app.services import indicios


def _evento(**cambios) -> dict:
    base = {
        "source_id": "seiscomp",
        "event_id": "seiscomp:000001",
        "source_event_id": "csn_sc62026vdkls",
        "event_time": "2026-10-28 15:23:36",
        "latitude": -52.857,
        "longitude": -71.570,
        "depth_km": 10.0,
        "magnitude": None,
        "analyst": "mdur",
        "raw_index": 2650,
        "raw": {},
    }
    base.update(cambios)
    return base


def _arribo(
    estacion: str,
    lat: float,
    lon: float,
    pick: str,
    residual: float,
    *,
    weight: float = 1.0,
    phase: str = "P",
    usada: bool = True,
    azimuth: float | None = None,
    raw: dict | None = None,
) -> dict:
    return {
        "source_id": "seiscomp",
        "event_id": "seiscomp:000001",
        "network": "C1",
        "station": estacion,
        "phase": phase,
        "pick_time": pick,
        "residual": residual,
        "weight": weight,
        "is_used_in_solution": usada,
        "azimuth": azimuth,
        "distance_km": None,
        "station_latitude": lat,
        "station_longitude": lon,
        "raw": raw or {},
    }


def _caso_mg04() -> list[dict]:
    return [
        _arribo("MG04", -52.857232, -71.569992, "2026-10-28 15:27:41.921878", 244.200065),
        _arribo("MG03", -51.670000, -71.570000, "2026-10-28 15:27:41.512964", 223.471888),
        _arribo("MG02", -51.430000, -71.570000, "2026-10-28 15:27:44.457146", 222.982285),
        _arribo("USHA", -50.150000, -71.570000, "2026-10-28 15:27:43.230404", 203.630270),
        _arribo("AY05", -45.000000, -71.570000, "2026-10-28 15:27:42.576141", 132.892849),
    ]


def _escribir(workspace: Path, source_id: str, eventos, arribos, sin_arribos=()) -> None:
    canonical.escribir_registros(
        canonical.ruta_canonica(workspace, source_id), eventos
    )
    canonical.escribir_registros(
        canonical.ruta_arribos(workspace, source_id), arribos
    )
    if sin_arribos:
        canonical.escribir_registros(
            canonical.ruta_estaciones_sin_arribos(workspace, source_id),
            sin_arribos,
        )


def test_detecta_caso_puntual_extremo_y_lo_marca_prioritario():
    resultado = indicios.evaluar_evento(
        _evento(),
        _caso_mg04(),
        source_id="seiscomp",
        con_cruce=True,
        sospechoso=True,
    )

    assert resultado["anomalia"] is True
    assert resultado["fuerza"] == "fuerte"
    assert resultado["patron"] == "puntual"
    assert resultado["contexto"] == "débil"
    assert resultado["extremo"] is True
    assert resultado["n_outliers"] == 5
    assert resultado["n_fuera_de_orden"] > 0
    assert resultado["revision_prioritaria"] is True
    assert resultado["prioridad"] == "Alta"
    assert resultado["prioridad_orden"] == 5
    assert resultado["max_residual_usado"] == "244.20"
    assert resultado["evidencia"]


def test_prioridad_combina_publicacion_solucion_y_fuerza():
    assert indicios.prioridad_evento(True, "fuerte", True) == "Alta"
    assert indicios.prioridad_evento(True, "débil", True) == "Alta"
    assert indicios.prioridad_evento(True, "", True) == "Alta"
    assert indicios.prioridad_evento(True, "fuerte", False) == "Media"
    assert indicios.prioridad_evento(True, "débil", False) == "Informativa"
    assert indicios.prioridad_evento(False, "fuerte", True) == "Baja"
    assert indicios.prioridad_evento(False, "débil", True) == "Informativa"
    assert indicios.prioridad_evento(True, "fuerte", None) == "Media"
    assert indicios.prioridad_evento(None, "fuerte", True) == "Sin evaluar"


def test_no_alarma_si_el_evento_no_esta_publicado():
    resultado = indicios.evaluar_evento(
        _evento(),
        _caso_mg04(),
        source_id="seiscomp",
        con_cruce=False,
        sospechoso=True,
    )

    assert resultado["anomalia"] is True
    assert resultado["revision_prioritaria"] is False
    assert resultado["cruce_eventquery"] is False
    assert resultado["prioridad"] == "Baja"
    assert resultado["prioridad_orden"] == 3


def test_patron_sistematico_con_contexto_fuerte():
    evento = _evento(
        event_id="seiscomp:000002",
        event_time="2020-01-01 00:00:00",
        latitude=0.0,
        longitude=0.0,
        source_event_id="ev-2",
    )
    arribos = [
        _arribo("A", 0.5, 0.0, "2020-01-01 00:00:10", 6.0, azimuth=0),
        _arribo("B", 0.4, 0.4, "2020-01-01 00:00:12", 7.0, azimuth=60),
        _arribo("C", 0.0, 0.5, "2020-01-01 00:00:14", 8.0, azimuth=120),
        _arribo("D", -0.5, 0.0, "2020-01-01 00:00:16", 6.5, azimuth=180),
        _arribo("E", -0.4, -0.4, "2020-01-01 00:00:18", 7.5, azimuth=240),
        _arribo("F", 0.0, -0.5, "2020-01-01 00:00:20", 8.5, azimuth=300),
    ]
    sin_arribos = [
        {"event_id": "seiscomp:000002", "network": "C1", "station": "G"},
        {"event_id": "seiscomp:000002", "network": "C1", "station": "H"},
    ]
    resultado = indicios.evaluar_evento(
        evento,
        arribos,
        sin_arribos,
        source_id="seiscomp",
        con_cruce=True,
        perfil_disponible=True,
        sospechoso=True,
    )

    assert resultado["fuerza"] == "fuerte"
    assert resultado["patron"] == "sistemático"
    assert resultado["contexto"] == "fuerte"
    assert resultado["extremo"] is False
    assert resultado["revision_prioritaria"] is True


def test_patron_sistematico_moderado_es_no_concluyente():
    evento = _evento(
        event_id="seiscomp:000004",
        event_time="2020-01-01 00:00:00",
        latitude=0.0,
        longitude=0.0,
        source_event_id="ev-4",
    )
    arribos = [
        _arribo("A", 0.5, 0.0, "2020-01-01 00:00:10", 2.5),
        _arribo("B", 0.4, 0.4, "2020-01-01 00:00:12", 2.8),
        _arribo("C", 0.0, 0.5, "2020-01-01 00:00:14", 3.0),
        _arribo("D", -0.5, 0.0, "2020-01-01 00:00:16", 3.2),
        _arribo("E", -0.4, -0.4, "2020-01-01 00:00:18", 3.1),
        _arribo("F", 0.0, -0.5, "2020-01-01 00:00:20", 2.9),
    ]
    resultado = indicios.evaluar_evento(
        evento,
        arribos,
        source_id="seiscomp",
        con_cruce=True,
        sospechoso=True,
        perfil_disponible=True,
    )

    assert resultado["n_outliers"] == 0
    assert resultado["fuerza"] == ""
    assert resultado["patron"] == "sistemático"
    assert "no concluyente" in resultado["resumen"]
    assert resultado["prioridad"] == "Alta"

    normal = indicios.evaluar_evento(
        evento,
        arribos,
        source_id="seiscomp",
        con_cruce=True,
        sospechoso=False,
        perfil_disponible=True,
    )
    assert normal["patron"] == "sistemático"
    assert normal["fuerza"] == ""
    assert normal["prioridad"] == "Informativa"


def test_detecta_pick_antes_del_origen():
    evento = _evento(
        event_id="seiscomp:000003",
        event_time="2020-01-01 00:00:00",
        latitude=0.0,
        longitude=0.0,
    )
    arribos = [
        _arribo("A", 0.5, 0.0, "2019-12-31 23:59:55", -10.0),
    ]
    resultado = indicios.evaluar_evento(
        evento, arribos, source_id="seiscomp", con_cruce=True
    )

    assert resultado["anomalia"] is True
    assert resultado["fuerza"] == "fuerte"
    assert resultado["patron"] == "pick_antes_origen"
    assert resultado["n_picks_antes_origen"] == 1


def test_peso_bajo_no_genera_indicio():
    evento = _evento(
        event_id="seiscomp:000004",
        event_time="2020-01-01 00:00:00",
        latitude=0.0,
        longitude=0.0,
    )
    arribos = [
        _arribo("A", 0.1, 0.0, "2020-01-01 00:00:05", 100.0, weight=0.1),
    ]
    resultado = indicios.evaluar_evento(
        evento, arribos, source_id="seiscomp", con_cruce=True
    )

    assert resultado["anomalia"] is False
    assert resultado["fuerza"] == ""
    assert resultado["revision_prioritaria"] is False
    assert resultado["n_outliers"] == 0


def test_peso_4_no_genera_indicio():
    evento = _evento(
        event_id="seiscomp:000006",
        event_time="2020-01-01 00:00:00",
        latitude=0.0,
        longitude=0.0,
    )
    arribos = [
        _arribo("TOQ0", 0.4, 0.0, "2020-01-01 00:00:06", -0.1, weight=1.4),
        _arribo(
            "AP01",
            1.3,
            0.0,
            "2020-01-01 00:00:20",
            7.27,
            weight=3.6e-22,
            raw={"peso": 3.6e-22},
        ),
        _arribo("PB12", 1.5, 0.0, "2020-01-01 00:00:16", 0.32, weight=1.37),
    ]
    resultado = indicios.evaluar_evento(
        evento, arribos, source_id="seiscomp", con_cruce=True
    )

    assert resultado["anomalia"] is False
    assert resultado["fuerza"] == ""
    assert resultado["n_fuera_de_orden"] == 0
    assert resultado["n_fuera_de_orden_debiles"] == 0
    assert resultado["evidencia"] == []
    assert resultado["evidencia_principal"] is None


def test_detecta_fuera_de_orden_debil_con_peso_3():
    evento = _evento(
        event_id="seiscomp:000007",
        event_time="2020-01-01 00:00:00",
        latitude=0.0,
        longitude=0.0,
    )
    arribos = [
        _arribo("TOQ0", 0.4, 0.0, "2020-01-01 00:00:06", -0.1, weight=1.4),
        _arribo(
            "AP01",
            1.3,
            0.0,
            "2020-01-01 00:00:20",
            7.27,
            weight=0.3,
            raw={"peso": 0.3},
        ),
        _arribo("PB12", 1.5, 0.0, "2020-01-01 00:00:16", 0.32, weight=1.37),
    ]
    resultado = indicios.evaluar_evento(
        evento, arribos, source_id="seiscomp", con_cruce=True
    )

    assert resultado["anomalia"] is True
    assert resultado["fuerza"] == "débil"
    assert resultado["patron"] == "fuera_de_orden_debil"
    assert resultado["n_fuera_de_orden_debiles"] == 1
    assert resultado["n_fuera_de_orden"] == 0
    assert resultado["revision_prioritaria"] is False
    debil = next(
        item
        for item in resultado["evidencia"]
        if item["tipo_indicio"] == "fuera_de_orden_debil"
    )
    assert debil["peso"] == "3"
    assert debil["residual"] == "+7.27"


def test_residual_alto_con_peso_3_genera_indicio_debil():
    evento = _evento(
        event_id="seiscomp:000008",
        event_time="2020-01-01 00:00:00",
        latitude=0.0,
        longitude=0.0,
    )
    arribos = [
        _arribo("E0", 0.5, 0.0, "2020-01-01 00:00:10", 10.0, weight=0.3),
        _arribo("E1", 1.0, 0.0, "2020-01-01 00:00:20", 1.0, weight=1.0),
        _arribo("E2", 1.5, 0.0, "2020-01-01 00:00:30", 1.0, weight=1.0),
    ]
    resultado = indicios.evaluar_evento(
        evento, arribos, source_id="seiscomp", con_cruce=True
    )

    assert resultado["anomalia"] is True
    assert resultado["fuerza"] == "débil"
    assert resultado["n_outliers"] == 1
    assert resultado["n_fuera_de_orden"] == 0
    assert resultado["evidencia_principal"]["peso"] == "3"
    assert resultado["evidencia_principal"]["tipo_indicio"] == "residual_alto"


def _tres_estaciones(**cambios_fase):
    """Tres estaciones con P y S para probar la evaluación por fase."""
    datos = []
    posiciones = [0.5, 1.0, 1.5]
    for indice, lat in enumerate(posiciones):
        p = cambios_fase.get("p", {})
        s = cambios_fase.get("s", {})
        datos.append(
            _arribo(
                f"E{indice}",
                lat,
                0.0,
                f"2020-01-01 00:00:{10 + indice * 10:02d}",
                p.get("residuales", (1.0, 1.0, 1.0))[indice],
                weight=p.get("pesos", (1.0, 1.0, 1.0))[indice],
                phase="P",
            )
        )
        datos.append(
            _arribo(
                f"E{indice}",
                lat,
                0.0,
                f"2020-01-01 00:00:{20 + indice * 10:02d}",
                s.get("residuales", (1.0, 1.0, 1.0))[indice],
                weight=s.get("pesos", (1.0, 1.0, 1.0))[indice],
                phase="S",
            )
        )
    return datos


def _fases_invertidas(resultado):
    return {
        item["fase"]
        for item in resultado["evidencia"]
        if item["tipo_indicio"] == "fuera_de_orden"
    }


def test_evalua_orden_inconsistente_solo_en_p():
    resultado = indicios.evaluar_evento(
        _evento(event_time="2020-01-01 00:00:00", latitude=0.0, longitude=0.0),
        _tres_estaciones(p={"residuales": (10.0, 1.0, 1.0)}),
        source_id="seiscomp",
    )

    assert resultado["n_fuera_de_orden"] > 0
    assert _fases_invertidas(resultado) == {"P"}


def test_evalua_orden_inconsistente_solo_en_s():
    resultado = indicios.evaluar_evento(
        _evento(event_time="2020-01-01 00:00:00", latitude=0.0, longitude=0.0),
        _tres_estaciones(s={"residuales": (10.0, 1.0, 1.0)}),
        source_id="seiscomp",
    )

    assert resultado["n_fuera_de_orden"] > 0
    assert _fases_invertidas(resultado) == {"S"}


def test_peso_4_en_p_evalua_solamente_la_s():
    resultado = indicios.evaluar_evento(
        _evento(event_time="2020-01-01 00:00:00", latitude=0.0, longitude=0.0),
        _tres_estaciones(
            p={"residuales": (10.0, 1.0, 1.0), "pesos": (1e-6, 1.0, 1.0)},
            s={"residuales": (10.0, 1.0, 1.0)},
        ),
        source_id="seiscomp",
    )

    assert resultado["n_fuera_de_orden"] > 0
    assert _fases_invertidas(resultado) == {"S"}


def test_peso_4_en_s_evalua_solamente_la_p():
    resultado = indicios.evaluar_evento(
        _evento(event_time="2020-01-01 00:00:00", latitude=0.0, longitude=0.0),
        _tres_estaciones(
            p={"residuales": (10.0, 1.0, 1.0)},
            s={"residuales": (10.0, 1.0, 1.0), "pesos": (1e-6, 1.0, 1.0)},
        ),
        source_id="seiscomp",
    )

    assert resultado["n_fuera_de_orden"] > 0
    assert _fases_invertidas(resultado) == {"P"}


def test_ambas_fases_con_peso_4_no_generan_indicio():
    resultado = indicios.evaluar_evento(
        _evento(event_time="2020-01-01 00:00:00", latitude=0.0, longitude=0.0),
        _tres_estaciones(
            p={"residuales": (10.0, 1.0, 1.0), "pesos": (1e-6, 1e-6, 1e-6)},
            s={"residuales": (10.0, 1.0, 1.0), "pesos": (1e-6, 1e-6, 1e-6)},
        ),
        source_id="seiscomp",
        con_cruce=True,
    )

    assert resultado["anomalia"] is False
    assert resultado["evidencia"] == []
    assert resultado["evidencia_principal"] is None


def test_marca_residual_temporal_desde_la_procedencia():
    arribos = [
        _arribo(
            "A",
            0.1,
            0.0,
            "2020-01-01 00:00:05",
            100.0,
            raw={"residual_fuente": "seisan", "residual_temporal": True},
        )
    ]
    resultado = indicios.evaluar_evento(
        _evento(event_id="seiscomp:000005"), arribos, source_id="seiscomp"
    )

    assert resultado["residual_temporal"] is True
    assert resultado["residual_fuentes"] == "seisan"


def test_genera_reportes_y_resumen(tmp_path):
    workspace = tmp_path / "ws"
    evento = _evento()
    _escribir(workspace, "seiscomp", [evento], _caso_mg04())
    atribucion = workspace / "datos" / "atribucion_seiscomp.csv"
    atribucion.parent.mkdir(parents=True)
    with atribucion.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.DictWriter(
            archivo, fieldnames=["fecha_local", "lat_local", "lon_local"]
        )
        escritor.writeheader()
        escritor.writerow(
            {
                "fecha_local": "2026-10-28 15:23:36",
                "lat_local": "-52.857",
                "lon_local": "-71.570",
            }
        )

    resumen = indicios.generar_indicios(workspace, ["seiscomp"], job_id="job-1")

    assert resumen["esquema"] == indicios.ESQUEMA_INDICIOS
    assert resumen["total"]["eventos"] == 1
    assert resumen["total"]["con_anomalia"] == 1
    assert resumen["total"]["con_anomalia_fuerte"] == 1
    assert resumen["total"]["con_anomalia_debil"] == 0
    assert resumen["total"]["revision_prioritaria"] == 1
    assert resumen["fuentes"]["seiscomp"]["soluciones_con_cruce"] == 1
    assert resumen["total"]["soluciones_con_cruce"] == 1
    assert resumen["total"]["eventos_referencia"] == 0

    filas = indicios.leer_indicios(workspace, "seiscomp")
    assert len(filas) == 1
    assert filas[0]["id_evento_fuente"] == "csn_sc62026vdkls"
    assert filas[0]["cruce_eventquery"] == "con_cruce"
    # El reporte no conoce la solución: con fase fuerte queda en calidad de
    # catálogo (Media), no en la prioridad de localización.
    assert filas[0]["revision_prioritaria"] == "Sí"
    assert filas[0]["fuerza"] == "fuerte"
    assert filas[0]["prioridad"] == "Media"
    assert filas[0]["prioridad_orden"] == "4"
    assert filas[0]["patron"] == "puntual"
    assert filas[0]["contexto"] == "débil"
    assert filas[0]["max_residual_usado"] == "244.20"
    assert filas[0]["resumen"].startswith("Puntual | residual +244.20 s")

    detalle = indicios.leer_detalle(workspace, "seiscomp", "seiscomp:000001")
    assert detalle
    assert any(item["tipo_indicio"] == "residual_alto" for item in detalle)

    assert indicios.leer_resumen(workspace) == resumen


def test_resumen_visible_filtra_por_analista(app, tmp_path):
    ana = User(username="ana", role="analista", analyst_code="ana", active=True)
    beto = User(username="beto", role="analista", analyst_code="beto", active=True)
    admin = User(username="admin", role="admin", active=True)
    for usuario in (ana, beto, admin):
        usuario.set_password("secret")
    db.session.add_all([ana, beto, admin])
    db.session.commit()

    workspace = tmp_path / "ws"
    evento_a = _evento(
        event_id="seiscomp:000101",
        event_time="2020-01-01 00:00:00",
        latitude=0.0,
        longitude=0.0,
        analyst="ana",
    )
    evento_b = _evento(
        event_id="seiscomp:000102",
        event_time="2020-01-01 00:00:00",
        latitude=0.0,
        longitude=0.0,
        analyst="beto",
    )
    arribo_a = dict(
        _arribo("A", 0.1, 0.0, "2020-01-01 00:00:05", 10.0),
        event_id="seiscomp:000101",
    )
    arribo_b = dict(
        _arribo("B", 0.2, 0.0, "2020-01-01 00:00:06", 10.0),
        event_id="seiscomp:000102",
    )
    _escribir(
        workspace,
        "seiscomp",
        [evento_a, evento_b],
        [arribo_a, arribo_b],
    )
    atribucion = workspace / "datos" / "atribucion_seiscomp.csv"
    atribucion.parent.mkdir(parents=True)
    with atribucion.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.DictWriter(
            archivo, fieldnames=["fecha_local", "lat_local", "lon_local"]
        )
        escritor.writeheader()
        escritor.writerow(
            {
                "fecha_local": "2020-01-01 00:00:00",
                "lat_local": "0.0",
                "lon_local": "0.0",
            }
        )

    indicios.generar_indicios(workspace, ["seiscomp"])

    visible_ana = indicios.resumen_visible(workspace, ["seiscomp"], ana)
    assert visible_ana["con_anomalia"] == 1
    assert visible_ana["con_anomalia_fuerte"] == 1
    assert visible_ana["soluciones_con_cruce"] == 1

    visible_admin = indicios.resumen_visible(workspace, ["seiscomp"], admin)
    assert visible_admin["con_anomalia"] == 2
    assert visible_admin["soluciones_con_cruce"] == 2


def test_central_derivada_no_cuenta_cruces(tmp_path):
    workspace = tmp_path / "ws"
    central = _evento(
        source_id="central",
        event_id="central:000001",
        source_event_id="central-1",
        analyst="central",
    )
    central_arribo = dict(
        _arribo("A", 0.1, 0.0, "2026-10-28 15:23:41", 10.0),
        source_id="central",
        event_id="central:000001",
    )
    referencia = _evento(
        source_id="eventquery",
        event_id="eventquery:000001",
        source_event_id="ref-1",
        analyst="eventquery_catalog",
    )
    _escribir(workspace, "central", [central], [central_arribo])
    _escribir(workspace, "eventquery", [referencia], [])

    atribucion = workspace / "datos" / "atribucion_central.csv"
    atribucion.parent.mkdir(parents=True)
    with atribucion.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.DictWriter(
            archivo, fieldnames=["fecha_local", "lat_local", "lon_local"]
        )
        escritor.writeheader()
        escritor.writerow(
            {
                "fecha_local": central["event_time"],
                "lat_local": central["latitude"],
                "lon_local": central["longitude"],
            }
        )

    resumen = indicios.generar_indicios(workspace, ["central"])

    assert resumen["fuentes"]["central"]["derived"] is True
    assert resumen["fuentes"]["central"]["soluciones_con_cruce"] == 0
    assert resumen["total"]["soluciones_con_cruce"] == 0
    assert resumen["total"]["eventos_referencia"] == 1
    filas = indicios.leer_indicios(workspace, "central")
    assert filas[0]["cruce_eventquery"] == "sin_evaluar"


def test_asegurar_indicios_regenera_si_cambia_el_esquema(tmp_path):
    workspace = tmp_path / "ws"
    ruta = indicios.ruta_resumen(workspace)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text('{"generado": "2026-01-01", "esquema": 1}', encoding="utf-8")

    resumen = indicios.asegurar_indicios(workspace, ["seiscomp"], job_id="job-2")

    assert resumen["esquema"] == indicios.ESQUEMA_INDICIOS
    assert resumen["job_id"] == "job-2"
    assert resumen["generado"] != "2026-01-01"


def test_estado_cruce_sin_atribucion_es_desconocido(tmp_path):
    workspace = tmp_path / "ws"
    assert (
        indicios.estado_cruce_eventquery(workspace, "seiscomp", _evento())
        is None
    )


def test_wadati_aparece_como_dato_informativo():
    picks = [
        ("E1", -30.0, -71.0, "2026-10-28 15:23:41", "2026-10-28 15:23:44.75"),
        ("E2", -30.2, -71.1, "2026-10-28 15:23:46", "2026-10-28 15:23:53.50"),
        ("E3", -30.4, -71.2, "2026-10-28 15:23:51", "2026-10-28 15:24:02.25"),
        ("E4", -30.6, -71.3, "2026-10-28 15:23:56", "2026-10-28 15:24:11.00"),
    ]
    arribos = []
    for estacion, lat, lon, pick_p, pick_s in picks:
        arribos.append(
            _arribo(estacion, lat, lon, pick_p, 0.0, phase="P")
        )
        arribos.append(
            _arribo(estacion, lat, lon, pick_s, 0.0, phase="S")
        )

    resultado = indicios.evaluar_evento(
        _evento(),
        arribos,
        source_id="seiscomp",
        con_cruce=True,
        sospechoso=False,
    )

    assert resultado["wadati_n"] == 4
    assert resultado["wadati_vp_vs"] == "1.75"
    assert resultado["wadati_r2"] == "1.00"
    assert resultado["wadati_dispersion"] == "0.00"
    assert resultado["wadati_calidad"] == "consistente"


def test_wadati_insuficiente_sin_pares_p_s():
    resultado = indicios.evaluar_evento(
        _evento(),
        _caso_mg04(),
        source_id="seiscomp",
        con_cruce=True,
        sospechoso=True,
    )

    assert resultado["wadati_n"] == 0
    assert resultado["wadati_vp_vs"] == ""
    assert resultado["wadati_calidad"] == "insuficiente"


def test_campos_de_indicios_incluyen_wadati():
    assert "wadati_n" in indicios.CAMPOS_EVENTO
    assert "wadati_vp_vs" in indicios.CAMPOS_EVENTO
    assert "wadati_r2" in indicios.CAMPOS_EVENTO
    assert "wadati_dispersion" in indicios.CAMPOS_EVENTO
    assert "wadati_calidad" in indicios.CAMPOS_EVENTO


def _atribucion_extra(workspace, nombre, filas):
    ruta = workspace / "datos" / nombre
    ruta.parent.mkdir(parents=True, exist_ok=True)
    campos = [
        "n_fila_eventquery",
        "fecha_eventquery",
        "lat_eventquery",
        "lon_eventquery",
        "fecha_local",
        "lat_local",
        "lon_local",
        "analista",
        "dt_seg",
        "dist_km",
        "fuente",
    ]
    with ruta.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=campos)
        escritor.writeheader()
        escritor.writerows(filas)


def test_coincidencias_extra_agrupa_por_referencia(tmp_path):
    workspace = tmp_path / "ws"
    _atribucion_extra(
        workspace,
        "atribucion_seiscomp.csv",
        [
            {
                "n_fila_eventquery": "10",
                "fecha_eventquery": "2026-11-01 00:00:00",
                "fecha_local": "2026-11-01 00:00:01",
                "lat_local": "-30.0",
                "lon_local": "-71.0",
                "analista": "ana",
                "dt_seg": "1.0",
                "dist_km": "0.4",
                "fuente": "seiscomp",
            },
            {
                "n_fila_eventquery": "11",
                "fecha_eventquery": "2026-11-02 00:00:00",
                "fecha_local": "2026-11-02 00:00:00",
                "lat_local": "-31.0",
                "lon_local": "-72.0",
                "analista": "ana",
                "dt_seg": "0.0",
                "dist_km": "0.2",
                "fuente": "seiscomp",
            },
            # Fila repetida: no debe sumar una solución.
            {
                "n_fila_eventquery": "10",
                "fecha_eventquery": "2026-11-01 00:00:00",
                "fecha_local": "2026-11-01 00:00:01",
                "lat_local": "-30.0",
                "lon_local": "-71.0",
                "analista": "ana",
                "dt_seg": "1.0",
                "dist_km": "0.4",
                "fuente": "seiscomp",
            },
        ],
    )
    _atribucion_extra(
        workspace,
        "atribucion_seisan.csv",
        [
            {
                "n_fila_eventquery": "10",
                "fecha_eventquery": "2026-11-01 00:00:00",
                "fecha_local": "2026-11-01 00:00:00",
                "lat_local": "-30.1",
                "lon_local": "-71.1",
                "analista": "beto",
                "dt_seg": "0.0",
                "dist_km": "0.8",
                "fuente": "seisan",
            }
        ],
    )

    datos = indicios.detalle_cruce(workspace)

    assert datos["extras"]["total"] == 1
    assert len(datos["extras"]["grupos"]) == 1
    grupo = datos["extras"]["grupos"][0]
    assert grupo["fila"] == "10"
    assert grupo["extra"] == 1
    assert len(grupo["soluciones"]) == 2
    assert {solucion["fuente"] for solucion in grupo["soluciones"]} == {
        "seiscomp",
        "seisan",
    }


def test_coincidencias_extra_reutiliza_artefacto(tmp_path):
    workspace = tmp_path / "ws"
    _atribucion_extra(
        workspace,
        "atribucion_seiscomp.csv",
        [
            {
                "n_fila_eventquery": "10",
                "fecha_eventquery": "2026-11-01 00:00:00",
                "fecha_local": "2026-11-01 00:00:01",
                "lat_local": "-30.0",
                "lon_local": "-71.0",
                "fuente": "seiscomp",
            },
            {
                "n_fila_eventquery": "10",
                "fecha_eventquery": "2026-11-01 00:00:00",
                "fecha_local": "2026-11-01 00:00:02",
                "lat_local": "-30.0",
                "lon_local": "-71.0",
                "fuente": "seiscomp",
            },
        ],
    )

    primero = indicios.leer_detalle_cruce(workspace)
    ruta = indicios.ruta_cruce_eventquery(workspace)
    assert ruta.is_file()
    assert primero["extras"]["total"] == 1

    segundo = indicios.leer_detalle_cruce(workspace)
    assert segundo["generado"] == primero["generado"]

    # Cambia la atribución: el artefacto debe recalcularse.
    _atribucion_extra(
        workspace,
        "atribucion_seiscomp.csv",
        [
            {
                "n_fila_eventquery": "10",
                "fecha_eventquery": "2026-11-01 00:00:00",
                "fecha_local": "2026-11-01 00:00:01",
                "lat_local": "-30.0",
                "lon_local": "-71.0",
                "fuente": "seiscomp",
            }
        ],
    )
    # Un artefacto con versión antigua también se recalcula.
    datos_version = json.loads(ruta.read_text(encoding="utf-8"))
    datos_version["version"] = 1
    ruta.write_text(
        json.dumps(datos_version, ensure_ascii=False), encoding="utf-8"
    )
    cuarto = indicios.leer_detalle_cruce(workspace)
    assert cuarto["version"] == indicios.VERSION_CRUCE

    tercero = indicios.leer_detalle_cruce(workspace)
    assert tercero["extras"]["total"] == 0


def _evento_canonico(
    source_id,
    event_id,
    event_time,
    lat,
    lon,
    raw_index,
    *,
    depth_km=42.0,
    magnitude=2.6,
    magnitude_type="MLv",
    raw=None,
):
    return {
        "source_id": source_id,
        "event_id": event_id,
        "source_event_id": "",
        "event_time": event_time,
        "latitude": lat,
        "longitude": lon,
        "depth_km": depth_km,
        "magnitude": magnitude,
        "magnitude_type": magnitude_type,
        "analyst": "ana",
        "raw_index": raw_index,
        "raw": raw or {},
    }


def test_sin_cruce_incluye_candidato_compatible(tmp_path):
    workspace = tmp_path / "ws"
    canonical.escribir_registros(
        canonical.ruta_canonica(workspace, "eventquery"),
        [
            _evento_canonico(
                "eventquery",
                "eventquery:000005",
                "2026-11-03 11:51:23",
                -22.59,
                -68.8,
                5,
                raw={"Referencia": "18 km al SE de Calama", "Percep.": "N"},
            )
        ],
    )
    canonical.escribir_registros(
        canonical.ruta_canonica(workspace, "seiscomp"),
        [
            _evento_canonico(
                "seiscomp",
                "seiscomp:000007",
                "2026-11-03 11:51:19",
                -22.59,
                -68.81,
                7,
            )
        ],
    )
    _atribucion_extra(workspace, "atribucion_seiscomp.csv", [])

    datos = indicios.detalle_cruce(workspace)

    assert datos["version"] == indicios.VERSION_CRUCE
    assert datos["sin_cruce"]["total"] == 1
    evento = datos["sin_cruce"]["eventos"][0]
    assert evento["fila"] == 5
    assert evento["evento"] == "eventquery:000005"
    assert evento["region"] == "18 km al SE de Calama"
    assert evento["candidato"]["evento_local"] == "seiscomp:000007"
    assert evento["candidato"]["dt_seg"] == 4.0
    assert evento["candidato"]["clasificacion"] == "compatible"
    assert evento["candidato"]["lat"] == -22.59
    assert evento["candidato"]["lon"] == -68.81
    assert evento["candidato"]["profundidad"] == 42.0
    assert evento["candidato"]["magnitud"] == 2.6
    assert evento["diferencias"]["profundidad"] == 0.0
    assert evento["diferencias"]["magnitud"] == 0.0
    assert evento["motivo"] == ""


def test_sin_cruce_omite_candidato_fuera_de_ventana(tmp_path):
    workspace = tmp_path / "ws"
    canonical.escribir_registros(
        canonical.ruta_canonica(workspace, "eventquery"),
        [
            _evento_canonico(
                "eventquery",
                "eventquery:000005",
                "2026-11-03 11:51:23",
                -22.59,
                -68.8,
                5,
            )
        ],
    )
    canonical.escribir_registros(
        canonical.ruta_canonica(workspace, "seiscomp"),
        [
            _evento_canonico(
                "seiscomp",
                "seiscomp:000007",
                "2026-11-03 11:52:23",
                -21.87,
                -68.8,
                7,
            )
        ],
    )
    _atribucion_extra(workspace, "atribucion_seiscomp.csv", [])

    datos = indicios.detalle_cruce(workspace)

    evento = datos["sin_cruce"]["eventos"][0]
    assert evento["candidato"] is None
    assert "120 s y 50 km" in evento["motivo"]


def test_sin_cruce_no_lista_referencias_cruzadas(tmp_path):
    workspace = tmp_path / "ws"
    canonical.escribir_registros(
        canonical.ruta_canonica(workspace, "eventquery"),
        [
            _evento_canonico(
                "eventquery",
                "eventquery:000005",
                "2026-11-03 11:51:23",
                -22.59,
                -68.8,
                5,
            )
        ],
    )
    _atribucion_extra(
        workspace,
        "atribucion_seiscomp.csv",
        [
            {
                "n_fila_eventquery": "5",
                "fecha_eventquery": "2026-11-03 11:51:23",
                "fecha_local": "2026-11-03 11:51:23",
                "lat_local": "-22.59",
                "lon_local": "-68.8",
                "fuente": "seiscomp",
            }
        ],
    )

    datos = indicios.detalle_cruce(workspace)

    assert datos["sin_cruce"]["total"] == 0


def test_sin_cruce_marca_profundidad_incompatible(tmp_path):
    workspace = tmp_path / "ws"
    canonical.escribir_registros(
        canonical.ruta_canonica(workspace, "eventquery"),
        [
            _evento_canonico(
                "eventquery",
                "eventquery:000005",
                "2026-11-03 11:51:23",
                -22.59,
                -68.8,
                5,
            )
        ],
    )
    canonical.escribir_registros(
        canonical.ruta_canonica(workspace, "seiscomp"),
        [
            _evento_canonico(
                "seiscomp",
                "seiscomp:000007",
                "2026-11-03 11:51:19",
                -22.59,
                -68.81,
                7,
                depth_km=82.9,
            )
        ],
    )
    _atribucion_extra(workspace, "atribucion_seiscomp.csv", [])

    evento = indicios.detalle_cruce(workspace)["sin_cruce"]["eventos"][0]

    assert evento["candidato"]["clasificacion"] == "cercano"
    assert "Δprofundidad 40.9 km" in evento["candidato"]["motivo_clasificacion"]


def test_sin_cruce_marca_magnitud_incompatible(tmp_path):
    workspace = tmp_path / "ws"
    canonical.escribir_registros(
        canonical.ruta_canonica(workspace, "eventquery"),
        [
            _evento_canonico(
                "eventquery",
                "eventquery:000005",
                "2026-11-03 11:51:23",
                -22.59,
                -68.8,
                5,
            )
        ],
    )
    canonical.escribir_registros(
        canonical.ruta_canonica(workspace, "seiscomp"),
        [
            _evento_canonico(
                "seiscomp",
                "seiscomp:000007",
                "2026-11-03 11:51:19",
                -22.59,
                -68.81,
                7,
                magnitude=3.4,
            )
        ],
    )
    _atribucion_extra(workspace, "atribucion_seiscomp.csv", [])

    evento = indicios.detalle_cruce(workspace)["sin_cruce"]["eventos"][0]

    assert evento["candidato"]["clasificacion"] == "cercano"
    assert "Δmagnitud 0.8" in evento["candidato"]["motivo_clasificacion"]


def test_sin_cruce_sin_profundidad_no_es_compatible(tmp_path):
    workspace = tmp_path / "ws"
    canonical.escribir_registros(
        canonical.ruta_canonica(workspace, "eventquery"),
        [
            _evento_canonico(
                "eventquery",
                "eventquery:000005",
                "2026-11-03 11:51:23",
                -22.59,
                -68.8,
                5,
            )
        ],
    )
    canonical.escribir_registros(
        canonical.ruta_canonica(workspace, "seiscomp"),
        [
            _evento_canonico(
                "seiscomp",
                "seiscomp:000007",
                "2026-11-03 11:51:19",
                -22.59,
                -68.81,
                7,
                depth_km=None,
            )
        ],
    )
    _atribucion_extra(workspace, "atribucion_seiscomp.csv", [])

    evento = indicios.detalle_cruce(workspace)["sin_cruce"]["eventos"][0]

    assert evento["candidato"]["clasificacion"] == "cercano"
    assert (
        "sin profundidad comparable"
        in evento["candidato"]["motivo_clasificacion"]
    )


def test_sin_cruce_tipo_de_magnitud_distinto_es_nota(tmp_path):
    workspace = tmp_path / "ws"
    canonical.escribir_registros(
        canonical.ruta_canonica(workspace, "eventquery"),
        [
            _evento_canonico(
                "eventquery",
                "eventquery:000005",
                "2026-11-03 11:51:23",
                -22.59,
                -68.8,
                5,
                magnitude_type="MLv",
            )
        ],
    )
    canonical.escribir_registros(
        canonical.ruta_canonica(workspace, "seiscomp"),
        [
            _evento_canonico(
                "seiscomp",
                "seiscomp:000007",
                "2026-11-03 11:51:19",
                -22.59,
                -68.81,
                7,
                magnitude_type="ML",
            )
        ],
    )
    _atribucion_extra(workspace, "atribucion_seiscomp.csv", [])

    evento = indicios.detalle_cruce(workspace)["sin_cruce"]["eventos"][0]

    assert evento["candidato"]["clasificacion"] == "compatible"
    assert "tipo de magnitud distinto" in evento["candidato"]["nota_magnitud"]
