"""El core debe formar parte del repositorio, no de un proyecto externo."""

from __future__ import annotations

from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CORE = RAIZ / "core"


def test_core_incorporado_tiene_modulos_principales():
    assert (CORE / "plotear.py").is_file()
    assert (CORE / "asigna_perfiles.py").is_file()
    assert (CORE / "sismicidad.py").is_file()
    assert (CORE / "fronteras.py").is_file()
    assert (CORE / "paths.py").is_file()
    assert (CORE / "README.md").is_file()


def test_core_incorporado_incluye_scripts_del_pipeline():
    for nombre in (
        "revisaselect.py",
        "revisacollect.py",
        "seiscomp_a_parametros.py",
        "proc_query_harz_2.py",
        "compara.py",
        "repetidos.py",
        "cruza_nopub.py",
    ):
        assert (CORE / nombre).is_file(), f"Falta {nombre} en core/"
