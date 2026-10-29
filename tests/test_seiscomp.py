"""Pruebas del servicio de exportación de SeisComp."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import psycopg2
import pytest

from app.services import runner_seiscomp
from app.services.seiscomp import configurada, exportar_ventana, probar_conexion

VARIABLES = (
    "SEISCOMP_DB_HOST",
    "SEISCOMP_DB_PORT",
    "SEISCOMP_DB_NAME",
    "SEISCOMP_DB_USER",
    "SEISCOMP_DB_PASSWORD",
)


def _limpiar(monkeypatch):
    for nombre in VARIABLES:
        monkeypatch.delenv(nombre, raising=False)


def _configurar(monkeypatch):
    _limpiar(monkeypatch)
    monkeypatch.setenv("SEISCOMP_DB_HOST", "10.54.217.69")
    monkeypatch.setenv("SEISCOMP_DB_PORT", "5432")
    monkeypatch.setenv("SEISCOMP_DB_NAME", "seiscomp2")
    monkeypatch.setenv("SEISCOMP_DB_USER", "rcs_ro")
    monkeypatch.setenv("SEISCOMP_DB_PASSWORD", "secreto")


def test_configurada_exige_host_usuario_y_clave(monkeypatch):
    _limpiar(monkeypatch)
    assert configurada() is False
    monkeypatch.setenv("SEISCOMP_DB_HOST", "10.54.217.69")
    monkeypatch.setenv("SEISCOMP_DB_USER", "rcs_ro")
    assert configurada() is False
    monkeypatch.setenv("SEISCOMP_DB_PASSWORD", "secreto")
    assert configurada() is True


def test_probar_conexion_sin_configuracion(monkeypatch):
    _limpiar(monkeypatch)

    resultado = probar_conexion()

    assert resultado["ok"] is False
    assert "SEISCOMP_DB_HOST" in resultado["error"]
    assert resultado["bases"] == []


def test_exportar_sin_configuracion(app, monkeypatch, tmp_path):
    _limpiar(monkeypatch)

    with pytest.raises(RuntimeError, match="SeisComp no está configurado"):
        exportar_ventana(
            "20261001000000",
            "20261031235959",
            tmp_path / "salida.csv",
        )


def test_exportar_consulta_todas_las_bases(app, monkeypatch, tmp_path):
    _configurar(monkeypatch)
    core = tmp_path / "core"
    core.mkdir()
    (core / "exporta_ventana_seiscomp.py").write_text("# exportador\n", encoding="utf-8")
    app.config["RCS_CORE_PATH"] = core

    llamada = {}

    def ejecutar(comando, **kwargs):
        llamada["comando"] = comando
        llamada["kwargs"] = kwargs
        salida = Path(comando[5])
        salida.write_text("a,b\n", encoding="utf-8")
        Path(str(salida) + ".completo").write_text("", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="[OK] 3 eventos\n", stderr="")

    monkeypatch.setattr("app.services.seiscomp.subprocess.run", ejecutar)
    log = []
    log_detalle = []
    salida = tmp_path / "files" / "seiscomp_20261001000000_20261031235959.csv"

    resultado = exportar_ventana(
        "20261001000000",
        "20261031235959",
        salida,
        radio_km=250,
        log=log.append,
        log_detalle=log_detalle.append,
    )

    assert resultado == salida
    comando = llamada["comando"]
    assert comando[0].endswith("python") or "python" in comando[0]
    assert comando[1].endswith("runner_seiscomp.py")
    assert comando[2].endswith("exporta_ventana_seiscomp.py")
    assert comando[-4:] == ["--base", "todas", "--radio-km", "250"]
    entorno = llamada["kwargs"]["env"]
    assert entorno["RCS_DB_HOST"] == "10.54.217.69"
    assert entorno["RCS_DB_DATABASE"] == "seiscomp2"
    assert entorno["RCS_DB_USER"] == "rcs_ro"
    assert entorno["RCS_DB_PASSWORD"] == "secreto"
    assert entorno["PGPORT"] == "5432"
    assert "PGOPTIONS" not in entorno
    assert any("Exportando datos de SeisComp" in linea for linea in log)
    assert any("Datos de SeisComp obtenidos" in linea for linea in log)
    assert any("3 eventos" in linea for linea in log_detalle)


def test_exportar_radio_invalido(app, monkeypatch, tmp_path):
    _configurar(monkeypatch)

    with pytest.raises(RuntimeError, match="radio"):
        exportar_ventana(
            "20261001000000",
            "20261031235959",
            tmp_path / "salida.csv",
            radio_km=0,
        )


def test_exportar_falla_si_no_deja_marca(app, monkeypatch, tmp_path):
    _configurar(monkeypatch)
    core = tmp_path / "core"
    core.mkdir()
    (core / "exporta_ventana_seiscomp.py").write_text("# exportador\n", encoding="utf-8")
    app.config["RCS_CORE_PATH"] = core
    monkeypatch.setattr(
        "app.services.seiscomp.subprocess.run",
        lambda comando, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    with pytest.raises(RuntimeError, match="no dejó el catálogo"):
        exportar_ventana(
            "20261001000000",
            "20261031235959",
            tmp_path / "salida.csv",
        )


def test_exportar_informa_codigo_de_error(app, monkeypatch, tmp_path):
    _configurar(monkeypatch)
    core = tmp_path / "core"
    core.mkdir()
    (core / "exporta_ventana_seiscomp.py").write_text("# exportador\n", encoding="utf-8")
    app.config["RCS_CORE_PATH"] = core
    monkeypatch.setattr(
        "app.services.seiscomp.subprocess.run",
        lambda comando, **kwargs: SimpleNamespace(
            returncode=3,
            stdout="",
            stderr="falló\n",
        ),
    )

    with pytest.raises(RuntimeError, match="código 3"):
        exportar_ventana(
            "20261001000000",
            "20261031235959",
            tmp_path / "salida.csv",
        )


def test_runner_fuerza_solo_lectura(monkeypatch):
    capturado = {}

    def connect(*args, **kwargs):
        capturado.update(kwargs)
        return object()

    monkeypatch.setattr(psycopg2, "connect", connect)
    runner_seiscomp.forzar_solo_lectura()

    psycopg2.connect("host=x", options="-c statement_timeout=1000")

    assert "statement_timeout=1000" in capturado["options"]
    assert "default_transaction_read_only=on" in capturado["options"]


def test_runner_no_duplica_la_opcion(monkeypatch):
    capturado = {}

    def connect(*args, **kwargs):
        capturado.update(kwargs)
        return object()

    monkeypatch.setattr(psycopg2, "connect", connect)
    runner_seiscomp.forzar_solo_lectura()

    psycopg2.connect("host=x", options="-c default_transaction_read_only=on")

    assert capturado["options"].count("default_transaction_read_only") == 1


def test_runner_permite_importar_modulos_del_core(tmp_path, monkeypatch, capsys):
    core = tmp_path / "core"
    core.mkdir()
    (core / "auxiliar.py").write_text("VALOR = 42\n", encoding="utf-8")
    (core / "script.py").write_text(
        "import auxiliar\nprint(f'valor={auxiliar.VALOR}')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(runner_seiscomp, "forzar_solo_lectura", lambda: None)
    monkeypatch.setattr(sys, "argv", ["runner", str(core / "script.py")])

    assert runner_seiscomp.main() == 0
    assert "valor=42" in capsys.readouterr().out
