"""Registro de fuentes de catálogo.

La referencia es eventquery. Las fuentes locales (SeisComp, Seisan y futuras)
se seleccionan por trabajo; la principal se elige entre ellas.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from .validators import validar_eventquery, validar_seisan, validar_seiscomp


@dataclass(frozen=True)
class Fuente:
    codigo: str
    etiqueta: str
    rol: str  # referencia | local
    archivo: str
    extensiones: tuple[str, ...]
    prefijo_compara: str
    validador: Callable
    permite_local: bool = True
    permite_ssh: bool = True

    @property
    def es_local(self) -> bool:
        return self.rol == "local"


FUENTES: dict[str, Fuente] = {
    "eventquery": Fuente(
        codigo="eventquery",
        etiqueta="Catálogo eventquery (publicado)",
        rol="referencia",
        archivo="eventquery_{inicio}_{fin}.csv",
        extensiones=("csv",),
        prefijo_compara="",
        validador=validar_eventquery,
        permite_ssh=True,
        permite_local=True,
    ),
    "seiscomp": Fuente(
        codigo="seiscomp",
        etiqueta="SeisComp",
        rol="local",
        archivo="seiscomp_{inicio}_{fin}.csv",
        extensiones=("csv",),
        prefijo_compara="seiscomp_",
        validador=validar_seiscomp,
        permite_ssh=True,
        permite_local=True,
    ),
    "seisan": Fuente(
        codigo="seisan",
        etiqueta="Seisan (select.out)",
        rol="local",
        archivo="select.out",
        extensiones=("out", "txt", "dat"),
        prefijo_compara="",
        validador=validar_seisan,
        permite_ssh=True,
        permite_local=True,
    ),
}

REFERENCIA = "eventquery"
ROLES_LOCALES = ("local_principal", "local_secundaria")


def fuente(codigo: str) -> Fuente:
    try:
        return FUENTES[codigo]
    except KeyError as exc:
        raise ValueError(f"Fuente de catálogo desconocida: {codigo}") from exc


def fuentes_locales() -> list[Fuente]:
    return [f for f in FUENTES.values() if f.es_local]


def etiqueta(codigo: str) -> str:
    return FUENTES.get(
        codigo, Fuente(codigo, codigo, "local", "", (), "", validar_eventquery)
    ).etiqueta


def etiquetas() -> dict[str, str]:
    return {codigo: fuente.etiqueta for codigo, fuente in FUENTES.items()}


def default_primary() -> str:
    valor = os.environ.get("DEFAULT_PRIMARY_LOCAL", "seiscomp")
    return valor if valor in FUENTES and FUENTES[valor].es_local else "seiscomp"


def nombre_archivo(codigo: str, inicio14: str, fin14: str) -> str:
    return fuente(codigo).archivo.format(inicio=inicio14, fin=fin14)


def nombre_no_publicados(codigo: str) -> str:
    if codigo == "seisan":
        return "no_pub_desde_2_5_estricto.csv"
    return f"no_pub_desde_2_5_{codigo}_estricto.csv"


def nombre_atribucion(codigo: str) -> str:
    return f"atribucion_{codigo}.csv"


def nombre_informe_no_actualizados(codigo: str) -> str:
    if codigo == "seisan":
        return "no_act_estricto.txt"
    return f"no_act_{codigo}_estricto.txt"


def prefijo_compara(codigo: str) -> str:
    return fuente(codigo).prefijo_compara
