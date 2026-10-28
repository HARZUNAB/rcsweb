"""Registro de formatos de catálogo.

Cada formato declara cómo normalizarse, qué capacidades aporta y cuál es su
archivo canónico. El registro no importa los adaptadores al arrancar: se cargan
de forma perezosa cuando se usa ese formato.
"""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass

from .schema import CAPACIDADES


@dataclass(frozen=True)
class Formato:
    codigo: str
    etiqueta: str
    rol: str  # referencia | local
    adaptador: str
    capacidades: frozenset[str]
    archivo: str
    extensiones: tuple[str, ...]
    prefijo_compara: str = ""
    permite_local: bool = True
    permite_ssh: bool = True
    disponible: bool = True

    @property
    def es_local(self) -> bool:
        return self.rol == "local"


FORMATOS: dict[str, Formato] = {
    "eventquery": Formato(
        codigo="eventquery",
        etiqueta="Eventquery (publicado)",
        rol="referencia",
        adaptador="app.domain.catalogs.adapters.eventquery",
        capacidades=frozenset({"eventos", "origenes", "magnitudes"}),
        archivo="eventquery_{inicio}_{fin}.csv",
        extensiones=("csv",),
    ),
    "seiscomp": Formato(
        codigo="seiscomp",
        etiqueta="SeisComp",
        rol="local",
        adaptador="app.domain.catalogs.adapters.seiscomp",
        capacidades=frozenset(
            {
                "eventos",
                "origenes",
                "magnitudes",
                "arribos",
                "inventario",
                "disponibilidad_ondas",
            }
        ),
        archivo="seiscomp_{inicio}_{fin}.csv",
        extensiones=("csv",),
        prefijo_compara="seiscomp_",
    ),
    "seisan": Formato(
        codigo="seisan",
        etiqueta="Seisan (select.out)",
        rol="local",
        adaptador="app.domain.catalogs.adapters.seisan",
        capacidades=frozenset({"eventos", "origenes", "magnitudes", "excluidos"}),
        archivo="select.out",
        extensiones=("out", "txt", "dat"),
    ),
}

REFERENCIA = "eventquery"


def formato(codigo: str) -> Formato:
    try:
        return FORMATOS[codigo]
    except KeyError as exc:
        raise ValueError(f"Formato de catálogo desconocido: {codigo}") from exc


def formatos_locales() -> list[Formato]:
    return [f for f in FORMATOS.values() if f.es_local and f.disponible]


def etiquetas() -> dict[str, str]:
    return {codigo: f.etiqueta for codigo, f in FORMATOS.items()}


def default_primary() -> str:
    valor = os.environ.get("DEFAULT_PRIMARY_LOCAL", "seiscomp")
    return valor if valor in FORMATOS and FORMATOS[valor].es_local else "seiscomp"


def capacidades_validas(capacidades) -> set[str]:
    return {c for c in (capacidades or ()) if c in CAPACIDADES}


def adaptador(codigo: str):
    """Instancia el adaptador del formato (import perezoso)."""
    modulo = importlib.import_module(formato(codigo).adaptador)
    return modulo.Adaptador()
