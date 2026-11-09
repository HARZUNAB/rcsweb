"""Registro de formatos de catálogo.

Cada formato declara cómo normalizarse, qué capacidades aporta y cuál es su
archivo canónico. El registro no importa los adaptadores al arrancar: se cargan
de forma perezosa cuando se usa ese formato.

Las claves del registro son identificadores internos de adaptador. No
representan nombres de fuente ni etiquetas visibles: el manifiesto define el
``id``, el ``label`` y el ``role`` de cada fuente. Ninguna otra parte de la app
compara estas claves para decidir nombres, colores o archivos.
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
    tipo: str = ""  # reference | select | export
    permite_local: bool = True
    permite_ssh: bool = True
    disponible: bool = True

    @property
    def es_local(self) -> bool:
        return self.rol == "local"


FORMATOS: dict[str, Formato] = {
    "referencia": Formato(
        codigo="referencia",
        etiqueta="Referencia publicada",
        rol="referencia",
        adaptador="app.domain.catalogs.adapters.eventquery",
        capacidades=frozenset(
            {"eventos", "origenes", "magnitudes", "percibidos"}
        ),
        archivo="eventquery_{inicio}_{fin}.csv",
        extensiones=("csv",),
        tipo="reference",
    ),
    "local_export": Formato(
        codigo="local_export",
        etiqueta="Fuente local (exportación)",
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
                "tensores",
            }
        ),
        archivo="seiscomp_{inicio}_{fin}.csv",
        extensiones=("csv",),
        prefijo_compara="seiscomp_",
        tipo="export",
    ),
    "local_select": Formato(
        codigo="local_select",
        etiqueta="Fuente local (select.out)",
        rol="local",
        adaptador="app.domain.catalogs.adapters.seisan",
        capacidades=frozenset(
            {"eventos", "origenes", "magnitudes", "excluidos", "tensores"}
        ),
        archivo="select.out",
        extensiones=("out", "txt", "dat"),
        tipo="select",
    ),
    "local_db": Formato(
        codigo="local_db",
        etiqueta="Fuente local (base de datos)",
        rol="local",
        adaptador="app.domain.catalogs.adapters.central",
        capacidades=frozenset(
            {"eventos", "origenes", "magnitudes", "tensores"}
        ),
        archivo="",
        extensiones=("csv",),
        tipo="db",
    ),
}

# Alias de compatibilidad para manifiestos y pruebas que usan los nombres
# históricos. No se usan en la lógica nueva.
ALIASES = {
    "eventquery": "referencia",
    "seiscomp": "local_export",
    "seisan": "local_select",
}

REFERENCIA = "referencia"


def _clave(codigo: str) -> str:
    return ALIASES.get(codigo, codigo)


def formato(codigo: str) -> Formato:
    try:
        return FORMATOS[_clave(codigo)]
    except KeyError as exc:
        raise ValueError(f"Formato de catálogo desconocido: {codigo}") from exc


def existe(codigo: str) -> bool:
    return _clave(codigo) in FORMATOS


def formatos_locales() -> list[Formato]:
    return [f for f in FORMATOS.values() if f.es_local and f.disponible]


def etiquetas() -> dict[str, str]:
    """Etiquetas internas de formato, más alias históricos."""
    salida = {codigo: f.etiqueta for codigo, f in FORMATOS.items()}
    for alias, codigo in ALIASES.items():
        salida[alias] = FORMATOS[codigo].etiqueta
    return salida


def default_primary() -> str:
    """Clave de formato local principal.

    Se conserva por compatibilidad. La app usa ``manifest.default_primary()``,
    que devuelve el id de la fuente definida en el manifiesto.
    """
    valor = os.environ.get("DEFAULT_PRIMARY_LOCAL", "local_export")
    clave = _clave(valor)
    if clave in FORMATOS and FORMATOS[clave].es_local:
        return clave
    locales = formatos_locales()
    return locales[0].codigo if locales else ""


def capacidades_validas(capacidades) -> set[str]:
    return {c for c in (capacidades or ()) if c in CAPACIDADES}


def adaptador(codigo: str):
    """Instancia el adaptador del formato (import perezoso)."""
    modulo = importlib.import_module(formato(codigo).adaptador)
    return modulo.Adaptador()
