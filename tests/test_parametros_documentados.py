"""El registro de parámetros debe cubrir el código y estar en el manual."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
TOML = RAIZ / "docs" / "parametros.toml"
ANEXO = RAIZ / "docs" / "anexos" / "D_parametros.md"


def test_check_parametros_documentados():
    resultado = subprocess.run(
        [sys.executable, "scripts/generar_parametros.py", "--check"],
        cwd=RAIZ,
        capture_output=True,
        text=True,
        check=False,
    )
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr


def test_registro_tiene_estructura_completa():
    datos = tomllib.loads(TOML.read_text(encoding="utf-8"))
    assert datos["version"] == 1
    assert datos["constantes"]["modulos"]
    parametros = datos["parametros"]
    assert len(parametros) >= 150
    assert {parametro["tipo"] for parametro in parametros} == {
        "entorno",
        "constante",
        "script",
    }
    for parametro in parametros:
        for campo in (
            "nombre",
            "tipo",
            "modulo",
            "simbolo",
            "ambito",
            "grupo",
            "seccion",
        ):
            assert parametro.get(campo), (
                f"{parametro.get('nombre')} sin {campo}"
            )


def test_anexo_d_tiene_secciones_e_indice():
    texto = ANEXO.read_text(encoding="utf-8")
    for seccion in (
        "D.1 Variables de entorno",
        "D.2 Constantes de módulos",
        "D.3 Parámetros de scripts",
        "D.4 Parámetros por trabajo",
        "D.5 Reglas y umbrales",
    ):
        assert seccion in texto
    for numero in range(1, 6):
        assert f"[[PAGEREF:_D_{numero}]]" in texto
