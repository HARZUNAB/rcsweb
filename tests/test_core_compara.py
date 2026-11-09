"""Pruebas de la comparación contra eventquery con la columna Publicado."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parent.parent / "core"
MODULOS = ("compara", "repetidos", "rutas", "prog")


@pytest.fixture()
def core(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(CORE))
    monkeypatch.chdir(tmp_path)
    for nombre in MODULOS:
        sys.modules.pop(nombre, None)
    yield
    for nombre in MODULOS:
        sys.modules.pop(nombre, None)


def test_indice_y_publicado(core):
    compara = importlib.import_module("compara")

    assert compara._indice_columna(
        ["", "Fecha_Hora", "Publicado", "Revisión"], "Publicado"
    ) == 2
    assert compara._indice_columna(
        ["", "Fecha_Hora", "publicado"], "Publicado"
    ) == 2
    assert compara._indice_columna(["", "Fecha_Hora"], "Publicado") is None
    assert compara._publicado("Sí") is True
    assert compara._publicado("No") is False
    assert compara._publicado("") is None


def test_publicados_sin_cruce_y_no_publicados(core, tmp_path):
    compara = importlib.import_module("compara")

    (tmp_path / "eventquery.csv").write_text(
        ",Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Referencia,Percep.\n"
        "0,2026-10-01 00:00:00,-30.0,-71.0,10.0,2.5,ML,Ref,N\n"
        "1,2026-10-01 00:05:00,-31.0,-72.0,15.0,3.0,ML,Ref,N\n",
        encoding="utf-8",
    )
    (tmp_path / "local.csv").write_text(
        ",Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista,Publicado\n"
        "0,2026-10-01 00:00:00,-30.0,-71.0,10.0,2.5,ML,eatl,No\n"
        "1,2026-10-01 00:05:00,-31.0,-72.0,15.0,3.2,ML,eatl,Sí\n"
        "2,2026-10-01 01:00:00,-32.0,-73.0,20.0,2.6,ML,eatl,Sí\n"
        "3,2026-10-01 02:00:00,-33.0,-74.0,25.0,2.7,ML,eatl,No\n"
        "4,2026-10-01 00:00:00,-40.0,-80.0,20.0,2.8,ML,eatl,Sí\n",
        encoding="utf-8",
    )

    compara.main(["compara.py", "eventquery.csv", "local.csv", "central_"])

    no_pub = (
        tmp_path / "datos/no_pub_desde_2_5_central_estricto.csv"
    ).read_text(encoding="utf-8")
    assert "02:00:00" in no_pub
    assert "01:00:00" not in no_pub
    assert "00:05:00" not in no_pub

    no_act = (tmp_path / "informes/no_act_central_estricto.txt").read_text(
        encoding="utf-8"
    )
    assert "00:05:00" in no_act

    sin_cruce = (
        tmp_path / "informes/publicados_sin_cruce_central_estricto.txt"
    ).read_text(encoding="utf-8")
    assert "01:00:00" in sin_cruce
    assert "00:00:00" in sin_cruce
    assert "00:05:00" not in sin_cruce
    assert "02:00:00" not in sin_cruce


def test_repetidos_acepta_prefijos(core, tmp_path):
    modulo = importlib.import_module("repetidos")

    (tmp_path / "eventquery.csv").write_text(
        ",Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Referencia,Percep.\n"
        "0,2026-10-01 00:00:00,-30.0,-71.0,10.0,2.5,ML,Ref,N\n",
        encoding="utf-8",
    )
    (tmp_path / "uno.csv").write_text(
        ",Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista\n"
        "0,2026-10-01 00:00:00,-30.0,-71.0,10.0,2.5,ML,eatl\n",
        encoding="utf-8",
    )
    (tmp_path / "dos.csv").write_text(
        ",Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista\n"
        "0,2026-10-01 00:00:00,-30.0,-71.0,10.0,2.5,ML,Jere\n",
        encoding="utf-8",
    )

    modulo.main(
        [
            "repetidos.py",
            "eventquery.csv",
            "uno.csv",
            "dos.csv",
            "--prefijos=central,seisan",
        ]
    )

    assert (tmp_path / "informes/rep_central_estricto.txt").is_file()
    assert (tmp_path / "informes/rep_seisan_estricto.txt").is_file()
    assert (tmp_path / "informes/rep_publica_estricto.txt").is_file()
