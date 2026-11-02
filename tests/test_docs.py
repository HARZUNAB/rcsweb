"""Pruebas de consistencia de los manuales y sus exportaciones DOCX."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
DOCS = RAIZ / "docs"


def _imagenes(markdown: str) -> list[str]:
    return re.findall(r"!\[[^\]]*\]\(([^)]+)\)", markdown)


def test_manuales_markdown_y_assets_existen():
    for nombre in ("manual_usuario", "manual_tecnico"):
        ruta = DOCS / f"{nombre}.md"
        assert ruta.is_file()
        for imagen in _imagenes(ruta.read_text(encoding="utf-8")):
            assert (DOCS / imagen).is_file(), f"Falta {imagen} en {nombre}"


def test_manuales_docx_incluyen_imagenes():
    for nombre, minimo in (("manual_usuario", 5), ("manual_tecnico", 1)):
        ruta = DOCS / f"{nombre}.docx"
        assert ruta.is_file()
        with zipfile.ZipFile(ruta) as archivo:
            nombres = archivo.namelist()
            assert "word/document.xml" in nombres
            imagenes = [
                item for item in nombres if item.startswith("word/media/")
            ]
            assert len(imagenes) >= minimo
