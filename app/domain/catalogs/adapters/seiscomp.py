"""Adaptador de SeisComp: exportación → catálogo plano."""

from __future__ import annotations

from pathlib import Path

from .base import Adaptador as Base
from .base import PasoPlan


def _verificar(workspace) -> None:
    ruta = Path(workspace) / "datos" / "seiscomp_parametros.csv"
    if not ruta.is_file() or ruta.stat().st_size <= 1:
        raise RuntimeError("La exportación de SeisComp no produjo soluciones.")


class Adaptador(Base):
    formato = "seiscomp"
    prefijo = "seiscomp_"
    capacidades = frozenset(
        {
            "eventos",
            "origenes",
            "magnitudes",
            "arribos",
            "inventario",
            "disponibilidad_ondas",
        }
    )

    def pasos(self, job, eventquery: str) -> list[PasoPlan]:
        return [
            PasoPlan(
                "convertir_seiscomp",
                "Convertir exportación SeisComp",
                "seiscomp_a_parametros.py",
                [f"seiscomp_{job.inicio14}_{job.fin14}.csv"],
                verificar=_verificar,
            )
        ]

    def catalogo(self, job, eventquery: str) -> str:
        return "datos/seiscomp_parametros.csv"
