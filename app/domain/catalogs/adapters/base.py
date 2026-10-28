"""Interfaz comum de los adaptadores de catálogo."""

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
    """Contrato que implementa cada formato."""

    formato: str = ""
    prefijo: str = ""
    capacidades: frozenset[str] = frozenset()

    def pasos(self, job, eventquery: str) -> list[PasoPlan]:
        raise NotImplementedError

    def catalogo(self, job, eventquery: str) -> str:
        """Ruta relativa del CSV plano normalizado de esta fuente."""
        raise NotImplementedError
