"""Compatibilidad con la API anterior de fuentes.

La definición real vive en ``app.domain.catalogs.registry``. Este módulo mantiene
los nombres que ya usan la web, el pipeline y los tests.
"""

from __future__ import annotations

from ..domain.catalogs.registry import (
    FORMATOS,
    REFERENCIA,
    Formato,
    adaptador,
    default_primary,
    etiquetas,
    formato,
    formatos_locales,
)

FUENTES = FORMATOS
Fuente = Formato


def fuente(codigo: str) -> Formato:
    return formato(codigo)


def fuentes_locales() -> list[Formato]:
    return formatos_locales()


def etiqueta(codigo: str) -> str:
    return FORMATOS.get(codigo, Formato(codigo, codigo, "local", "", frozenset(), "", ())).etiqueta


def nombre_archivo(codigo: str, inicio14: str, fin14: str) -> str:
    return formato(codigo).archivo.format(inicio=inicio14, fin=fin14)


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
    return formato(codigo).prefijo_compara


def capacidades(codigo: str) -> frozenset[str]:
    return formato(codigo).capacidades


__all__ = [
    "FUENTES",
    "REFERENCIA",
    "Fuente",
    "adaptador",
    "capacidades",
    "default_primary",
    "etiqueta",
    "etiquetas",
    "formato",
    "formatos_locales",
    "fuente",
    "nombre_archivo",
    "nombre_atribucion",
    "nombre_informe_no_actualizados",
    "nombre_no_publicados",
    "prefijo_compara",
]
