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
    formato = "local_select"
    tipo = "select"
    prefijo = ""
    prefijo_repetidos = "seisan"
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

    def catalogo(self, job, referencia: str) -> str:
        return "datos/salida_collect.csv"

    def prefijo_salida(self, source_id: str) -> str:
        return ""

    def archivo_no_publicados(self, source_id: str) -> str:
        return "no_pub_desde_2_5_estricto.csv"

    def archivo_no_actualizados(self, source_id: str) -> str:
        return "no_act_estricto.txt"
