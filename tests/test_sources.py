"""Pruebas del registro de fuentes y de los validadores."""

from __future__ import annotations

from datetime import datetime

from app.services.sources import (
    default_primary,
    fuente,
    fuentes_locales,
    nombre_atribucion,
    nombre_no_publicados,
)
from app.services.validators import validar_fuente

INICIO = datetime(2026, 10, 1)
FIN = datetime(2026, 10, 31)


def test_registro_de_fuentes():
    assert default_primary() == "seiscomp"
    assert [f.codigo for f in fuentes_locales()] == [
        "local_export",
        "local_select",
        "local_db",
    ]
    assert fuente("eventquery").rol == "referencia"
    assert not fuente("eventquery").es_local


def test_nombres_de_salida():
    assert nombre_no_publicados("seisan") == "no_pub_desde_2_5_estricto.csv"
    assert nombre_no_publicados("seiscomp") == "no_pub_desde_2_5_seiscomp_estricto.csv"
    assert nombre_atribucion("seiscomp") == "atribucion_seiscomp.csv"


def test_validar_eventquery(samples):
    resultado = validar_fuente(
        "eventquery",
        samples / "eventquery_20261001000000_20261031235959.csv",
        INICIO,
        FIN,
    )

    assert resultado["ok"] is True
    assert resultado["eventos"] == 4
    assert resultado["errores"] == []


def test_validar_eventquery_formato_nuevo(tmp_path):
    ruta = tmp_path / "eventquery_nuevo.csv"
    ruta.write_text(
        "time,latitude,longitude,depth [km],magnitude,magnitude_type,region_name,felt\n"
        "2026-10-02T12:00:00Z,-22.16,-68.60,105.7,2.7,MLv,Calama,f\n"
        "2026-10-03T12:00:00Z,-21.06,-68.87,124.5,2.6,MLv,Collahuasi,t\n",
        encoding="utf-8",
    )

    resultado = validar_fuente("eventquery", ruta, INICIO, FIN)

    assert resultado["ok"] is True
    assert resultado["eventos"] == 2
    assert resultado["errores"] == []


def test_validar_seisan(samples):
    resultado = validar_fuente("seisan", samples / "select.out", INICIO, FIN)

    assert resultado["ok"] is True
    assert resultado["eventos"] == 5
    assert resultado["errores"] == []


def test_validar_seisan_formato_crudo(tmp_path):
    archivo = tmp_path / "select.out"
    archivo.write_text(
        " 2025  326 0024 19.2QL -21.081 -69.000112.6  GUC 10 0.2 2.7LGUC                1\n"
        " 2025-03-26-0024-19M.GUC___136                                                 6\n"
        " 2025  326 0115 20.20L -22.000 -70.000 10.0             3.2L                   1\n"
        " 2025-03-26-0115-20M.GUC___033                                                 6\n",
        encoding="latin-1",
    )

    resultado = validar_fuente(
        "seisan",
        archivo,
        datetime(2025, 3, 26),
        datetime(2025, 3, 31),
    )

    assert resultado["ok"] is True
    assert resultado["eventos"] == 2
    assert resultado["desde"].startswith("2025-03-26")
    assert resultado["errores"] == []


def test_validar_seiscomp(samples):
    resultado = validar_fuente(
        "seiscomp",
        samples / "seiscomp_20261001000000_20261031235959.csv",
        INICIO,
        FIN,
    )

    assert resultado["ok"] is True
    assert resultado["eventos"] == 4
    assert resultado["errores"] == []


def test_validar_archivo_inexistente(tmp_path):
    resultado = validar_fuente("seisan", tmp_path / "no_existe.out", INICIO, FIN)

    assert resultado["ok"] is False
    assert resultado["errores"]


def test_validar_eventquery_sin_columnas(tmp_path):
    ruta = tmp_path / "malo.csv"
    ruta.write_text("a,b\n1,2\n", encoding="utf-8")

    resultado = validar_fuente("eventquery", ruta, INICIO, FIN)

    assert resultado["ok"] is False
    assert any("columnas" in error.lower() for error in resultado["errores"])


def test_validar_seiscomp_sin_eventos(tmp_path):
    ruta = tmp_path / "seiscomp.csv"
    ruta.write_text(
        "ot_utc,latitud,longitud,profundidad_km,magnitud,tipo_magnitud,operador\n",
        encoding="utf-8",
    )

    resultado = validar_fuente("seiscomp", ruta, INICIO, FIN)

    assert resultado["ok"] is False
