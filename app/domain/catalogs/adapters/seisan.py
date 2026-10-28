"""Adaptador de Seisan: select.out → catálogo plano."""

from __future__ import annotations

from pathlib import Path

from .base import Adaptador as Base
from .base import PasoPlan


def _verificar(workspace) -> None:
    ruta = Path(workspace) / "datos" / "salida_collect.csv"
    if not ruta.is_file() or ruta.stat().st_size <= 1:
        raise RuntimeError("select.out no produjo eventos analizables.")


class Adaptador(Base):
    formato = "seisan"
    prefijo = ""
    capacidades = frozenset({"eventos", "origenes", "magnitudes", "excluidos"})

    def pasos(self, job, eventquery: str) -> list[PasoPlan]:
        return [
            PasoPlan("normalizar_seisan", "Procesar select.out", "revisaselect.py"),
            PasoPlan(
                "armar_catalogo",
                "Armar catálogo local",
                "revisacollect.py",
                verificar=_verificar,
            ),
        ]

    def catalogo(self, job, eventquery: str) -> str:
        return "datos/salida_collect.csv"
