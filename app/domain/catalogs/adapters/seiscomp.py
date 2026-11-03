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
    formato = "local_export"
    tipo = "export"
    prefijo = "seiscomp_"
    prefijo_repetidos = "seiscomp"
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

    def catalogo(self, job, referencia: str) -> str:
        return "datos/seiscomp_parametros.csv"

    def archivo_no_publicados(self, source_id: str) -> str:
        return "no_pub_desde_2_5_seiscomp_estricto.csv"

    def archivo_no_actualizados(self, source_id: str) -> str:
        return "no_act_seiscomp_estricto.txt"
