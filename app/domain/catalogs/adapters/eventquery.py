"""Adaptador de eventquery: catálogo publicado de referencia."""

from __future__ import annotations

from .base import Adaptador as Base
from .base import PasoPlan


def _verificar(workspace, nombre: str) -> None:
    from pathlib import Path

    ruta = Path(workspace) / "datos" / f"new_2_{nombre}"
    if not ruta.is_file() or ruta.stat().st_size <= 1:
        raise RuntimeError("El catálogo eventquery no produjo eventos válidos.")


class Adaptador(Base):
    formato = "eventquery"

    def pasos(self, job, eventquery: str) -> list[PasoPlan]:
        return [
            PasoPlan(
                "normalizar_eventquery",
                "Normalizar catálogo eventquery",
                "proc_query_harz_2.py",
                [eventquery, "trabajo/salida.dat"],
                verificar=lambda ws: _verificar(ws, eventquery),
            )
        ]

    def catalogo(self, job, eventquery: str) -> str:
        return f"datos/new_2_{eventquery}"
