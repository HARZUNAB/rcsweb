"""El Anexo A debe cubrir las fuentes reales del manifiesto."""

from __future__ import annotations

import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ANEXO = RAIZ / "docs" / "anexos" / "A_fuentes_y_adaptadores.md"
MANIFIESTO = RAIZ / "app" / "domain" / "catalogs" / "sources.json"
ADAPTADORES = RAIZ / "app" / "domain" / "catalogs" / "adapters"


def _texto() -> str:
    return ANEXO.read_text(encoding="utf-8")


def test_anexo_menciona_todas_las_fuentes_del_manifiesto():
    datos = json.loads(MANIFIESTO.read_text(encoding="utf-8"))
    texto = _texto()
    for fuente in datos["sources"]:
        assert fuente["id"] in texto, fuente["id"]
        assert fuente["label"] in texto, fuente["label"]


def test_anexo_menciona_los_formatos_de_los_adaptadores():
    texto = _texto()
    formatos = set()
    for ruta in ADAPTADORES.glob("*.py"):
        if ruta.name in {"__init__.py", "base.py", "residuals.py"}:
            continue
        contenido = ruta.read_text(encoding="utf-8")
        coincidencia = re.search(r'formato\s*=\s*"([^"]+)"', contenido)
        if coincidencia:
            formatos.add(coincidencia.group(1))
    assert formatos
    for formato in formatos:
        assert formato in texto, formato


def test_anexo_documenta_el_flujo_de_seisan():
    texto = _texto()
    for marca in (
        "select.inp",
        "select.out",
        "revisaselect.py",
        "revisacollect.py",
        "STATION*.HYP",
        "CATALOGOS_SSH_HOST",
        "CATALOGOS_SSH_USER",
        "core_data/plantillas/select.inp",
        "type -P select",
        "Latin-1",
    ):
        assert marca in texto, marca
    assert "no es una base de datos" in texto.lower()
    assert "no tiene tablas ni sql consultable" in texto.lower()


def test_anexo_documenta_el_catalogo_extendido_y_su_descarga():
    texto = _texto()
    for marca in (
        "origin_quality",
        "origin_uncertainty",
        "origin_metadata",
        "magnitude_metadata",
        "eventos.json",
        "estaciones_resumen.csv",
        "RCS_CATALOGO_COMPLETO_ACTIVO",
        "distance_km_calc",
        "pick_uncertainty",
    ):
        assert marca in texto, marca


def test_anexo_esta_integrado_en_el_generador_y_el_manual():
    generador = (RAIZ / "scripts" / "generar_docs.py").read_text(
        encoding="utf-8"
    )
    assert "anexos/A_fuentes_y_adaptadores.md" in generador
    manual = (RAIZ / "docs" / "manual_tecnico.md").read_text(
        encoding="utf-8"
    )
    assert "Anexo A.4" in manual
    assert "Anexo A.7" in manual
