"""Interfaz común de los adaptadores de catálogo."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class PasoPlan:
    clave: str
    titulo: str
    script: str | None
    args: list[str] = field(default_factory=list)
    verificar: Callable | None = None
    post: Callable | None = None
    condicion: Callable | None = None


class Adaptador:
    """Contrato que implementa cada formato.

    El adaptador es el único lugar que conoce los nombres de archivo, scripts y
    claves que espera el core. La aplicación solo usa ``id`` y ``label`` del
    manifiesto.
    """

    formato: str = ""
    tipo: str = ""  # reference | select | export
    prefijo: str = ""
    prefijo_repetidos: str = ""
    # Etiqueta genérica que usa repetidos.py cuando hay una sola fuente local
    # que no es un select.out. Es un detalle del core, no un nombre de fuente.
    prefijo_repetidos_core: str = "seisan"
    capacidades: frozenset[str] = frozenset()
    # Clave de color que espera el renderizador del core, si difiere del label.
    render_fuente: str = ""

    def pasos(self, job, referencia: str) -> list[PasoPlan]:
        raise NotImplementedError

    def catalogo(self, job, referencia: str) -> str:
        """Ruta relativa del CSV plano normalizado de esta fuente."""
        raise NotImplementedError

    def prefijo_salida(self, source_id: str) -> str:
        return self.prefijo or f"{source_id}_"

    def archivo_no_publicados(self, source_id: str) -> str:
        return f"no_pub_desde_2_5_{self.prefijo_salida(source_id)}estricto.csv"

    def archivo_no_actualizados(self, source_id: str) -> str:
        prefijo = self.prefijo or f"{source_id}_"
        return f"no_act_{prefijo}estricto.txt"

    def archivo_repetidos(self, source_id: str, sufijo: str) -> str:
        prefijo = self.prefijo_repetidos or source_id
        return f"rep_{prefijo}_{sufijo}.txt"

    def archivo_repetidos_final(self, source_id: str, sufijo: str) -> str:
        return f"rep_{source_id}_{sufijo}.txt"

    def archivo_atribucion(self, source_id: str) -> str:
        return f"atribucion_{source_id}.csv"
