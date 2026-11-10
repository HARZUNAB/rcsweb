"""Pruebas de los arribos de Seisan desde select.out."""

from __future__ import annotations

import csv
from datetime import datetime

from app.domain.catalogs import arribos_csv
from app.domain.catalogs.adapters import seisan
from app.domain.catalogs.canonical import (
    escribir_desde_csv,
    escribir_extensiones,
    leer_canonico,
)
from app.services.station_review import revisar_evento

SELECT_OUT = """ 2025  326 0024 19.2QL -21.081 -69.000112.6  GUC 10 0.2 2.7LGUC                1
 GAP= 93        0.67       2.1     2.8  4.9 -0.5597E-01 -0.3963E+01 -0.2166E+01E
 2025-03-26-0024-19M.GUC___136                                                 6
 281858 1000727206a0c3fb8e7e7071193557ea                                     ID3
                                                           67e3493348b741 CSNID3
 ACTION:UP  25-03-25 21:44 OP:maca STATUS:               ID:20250326002419     I
 STAT SP IPHASW D HRMM SECON CODA AMPLIT PERI AZIMU VELO SNR AR TRES W  DIS CAZ7
 PB01 HZ IP     C  024 35.16                             152   -0.2510 50.8 275
 PB01 HN ES        024 47.43                             152   -0.3210 50.8 275
 PB01 HE  IAML     024 49.05       243.5 0.13                          50.8 275
 PB09 HZ IP        024 38.24                             139    0.1310 83.1 198

"""

STATION = "  PB012102.59S 6929.24W 900 +0.16\n"


def _job():
    return type(
        "Job",
        (),
        {"inicio14": "20250326000000", "fin14": "20250331235959"},
    )()


def _workspace(tmp_path, monkeypatch):
    estaciones = tmp_path / "datseisan"
    estaciones.mkdir()
    (estaciones / "STATION0.HYP").write_text(STATION, encoding="latin-1")
    monkeypatch.setenv("RCS_SEISAN_STATIONS_DIR", str(estaciones))

    workspace = tmp_path / "ws"
    (workspace / "datos").mkdir(parents=True)
    (workspace / "select.out").write_text(SELECT_OUT, encoding="latin-1")
    with (workspace / "datos" / "salida_collect.csv").open(
        "w", encoding="utf-8", newline=""
    ) as archivo:
        escritor = csv.writer(archivo)
        escritor.writerow(
            ["", "Fecha_Hora", "Latitud", "Longitud", "Prof.", "Mag.", "Tipo_mag.", "Analista"]
        )
        escritor.writerow(
            [
                0,
                "2025-03-26  00:24:19",
                -21.081,
                -69.000,
                112.6,
                2.7,
                "ML",
                "maca",
            ]
        )
    return workspace


def test_normalizar_fase_de_seisan():
    assert arribos_csv.normalizar_fase("IP") == "P"
    assert arribos_csv.normalizar_fase("EP") == "P"
    assert arribos_csv.normalizar_fase("ES") == "S"
    assert arribos_csv.normalizar_fase("ES   4") == "S"
    assert arribos_csv.normalizar_fase("IAML") == ""
    assert arribos_csv.normalizar_fase("PN") == "PN"


def test_parsear_canal_nslco():
    assert arribos_csv.parsear_canal("C1.PB02..HHZ") == ("C1", "PB02", "", "HHZ")
    assert arribos_csv.parsear_canal(".SAN..SE") == ("", "SAN", "", "SE")
    assert arribos_csv.parsear_canal("BL.PLTB..HHZ") == ("BL", "PLTB", "", "HHZ")


def test_bloques_select_out_lee_fases_y_descarta_amplitudes():
    from pathlib import Path

    ruta = Path("/tmp/opencode") / "select_prueba.out"
    ruta.write_text(SELECT_OUT, encoding="latin-1")
    bloques = seisan._bloques_select_out(ruta)

    assert len(bloques) == 1
    bloque = bloques[0]
    assert bloque["instante"] == datetime(2025, 3, 26, 0, 24, 19, 200000)
    assert bloque["operador"] == "maca"
    assert [fase["fase"] for fase in bloque["fases"]] == ["P", "S", "P"]
    assert bloque["fases"][0]["estacion"] == "PB01"
    assert bloque["fases"][0]["residual"] == -0.25
    assert bloque["fases"][0]["distancia"] == 50.8
    assert bloque["fases"][0]["llegada"] == datetime(
        2025, 3, 26, 0, 24, 35, 160000
    )


def test_instante_encabezado_usa_la_hora_del_evento_no_la_del_id():
    from app.domain.catalogs.adapters.seisan import _instante_encabezado

    # El ID de este evento dice 06:24:44, pero el encabezado dice 06:24:34.9.
    # El catálogo normalizado usa la hora del encabezado.
    linea = (
        " 2025  326 0624 34.9QL -24.162 -67.302204.5  GUC  7 0.3 3.5LGUC"
        "                1"
    )
    assert _instante_encabezado(linea) == datetime(
        2025, 3, 26, 6, 24, 34, 900000
    )

    linea = " 2026 11 1  019 52.0 L -29.812 -71.603 61.3"
    assert _instante_encabezado(linea) == datetime(2026, 11, 1, 0, 19, 52)


def test_preparar_arribos_escribe_canonico_y_revisa(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path, monkeypatch)
    adaptador = seisan.Adaptador()
    adaptador.source_id = "seisan"
    job = _job()

    adaptador._preparar_arribos(job, workspace)

    ruta_fases = workspace / adaptador._ruta_fases(job)
    assert ruta_fases.is_file()
    with ruta_fases.open(encoding="utf-8") as archivo:
        filas = list(csv.DictReader(archivo))
    assert len(filas) == 3
    pb01 = [fila for fila in filas if fila["estacion"] == "PB01"]
    assert len(pb01) == 2
    assert pb01[0]["fase"] == "P"
    assert pb01[0]["id_evento"] == "0"
    assert pb01[0]["est_lat"] == "-21.043166666666668"
    assert pb01[0]["est_lista"] == "STATION0.HYP"
    assert pb01[0]["est_vigencia"] == "current"
    pb09 = [fila for fila in filas if fila["estacion"] == "PB09"][0]
    assert pb09["est_lat"] == ""
    assert adaptador.extensiones(job, "", workspace) == {
        "arribos": adaptador._ruta_fases(job)
    }

    escribir_desde_csv(
        workspace, "seisan", "seisan", workspace / "datos" / "salida_collect.csv"
    )
    escribir_extensiones(
        workspace,
        "seisan",
        "seisan",
        {"arribos": adaptador._ruta_fases(job)},
    )
    eventos = leer_canonico(workspace, "seisan")
    assert eventos[0]["source_event_id"] == "0"
    revision = revisar_evento(workspace, "seisan", eventos[0])
    assert revision["estado"] == "ok"
    assert revision["tiene_coordenadas"] is True
    assert revision["tiene_tiempos"] is True
    estaciones = {punto["estacion"] for punto in revision["estaciones_mapa"]}
    assert "PB01" in estaciones
    assert "PB09" not in estaciones
    pb01 = next(
        punto
        for punto in revision["estaciones_mapa"]
        if punto["estacion"] == "PB01"
    )
    assert pb01["est_lista"] == "STATION0.HYP"
    assert pb01["est_vigencia"] == "current"
    assert pb01["software"] == "seisan"


def test_revisar_fila_seisan_en_repetidos(tmp_path, monkeypatch):
    from app.services.station_review import revisar_fila

    workspace = _workspace(tmp_path, monkeypatch)
    adaptador = seisan.Adaptador()
    adaptador.source_id = "seisan"
    job = _job()
    adaptador._preparar_arribos(job, workspace)
    escribir_desde_csv(
        workspace, "seisan", "seisan", workspace / "datos" / "salida_collect.csv"
    )
    escribir_extensiones(
        workspace,
        "seisan",
        "seisan",
        {"arribos": adaptador._ruta_fases(job)},
    )

    revision = revisar_fila(
        workspace,
        "repetidos",
        "seisan_estricto",
        {
            "fecha_hora": "2025-03-26 00:24:19",
            "latitud": "-21.081",
            "longitud": "-69.000",
        },
    )

    assert revision is not None
    assert revision["tiene_coordenadas"] is True
    assert revision["tiene_tiempos"] is True
    assert any(
        punto["estacion"] == "PB01" for punto in revision["estaciones_mapa"]
    )
