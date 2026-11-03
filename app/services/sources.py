"""Resolución de fuentes y nombres internos.

La identidad visible de una fuente vive en el manifiesto (``id``, ``label``,
``role``). El formato solo se usa para elegir el adaptador y para los nombres
de archivo que exige el core. Ninguna función de este módulo compara el nombre
de una fuente con un formato.
"""

from __future__ import annotations

from ..domain.catalogs import manifest as fuentes_manifest
from ..domain.catalogs.registry import (
    FORMATOS,
    REFERENCIA,
    Formato,
)
from ..domain.catalogs.registry import (
    adaptador as _adaptador_formato,
)
from ..domain.catalogs.registry import (
    default_primary as _default_primary_formato,
)
from ..domain.catalogs.registry import (
    etiquetas as _etiquetas_formato,
)
from ..domain.catalogs.registry import (
    formato as _formato,
)
from ..domain.catalogs.registry import (
    formatos_locales as _formatos_locales,
)

# Compatibilidad: antes ``FUENTES`` era el registro de formatos.
FUENTES = FORMATOS
Fuente = Formato


def definicion(codigo: str):
    """Fuente del manifiesto por id, o ``None``."""
    return fuentes_manifest.por_id(codigo)


def formato(codigo: str) -> str:
    """Clave de formato para un id de fuente o para una clave de formato."""
    fuente = definicion(codigo)
    if fuente is not None:
        return fuente.format
    return _formato(codigo).codigo


def fuente(codigo: str) -> Formato:
    return _formato(formato(codigo))


def adaptador(codigo: str):
    return _adaptador_formato(formato(codigo))


def locales() -> list[str]:
    return [fuente.id for fuente in fuentes_manifest.locales()]


def referencia() -> str:
    return fuentes_manifest.referencia().id


def es_referencia(codigo: str) -> bool:
    fuente_def = definicion(codigo)
    if fuente_def is not None:
        return fuente_def.es_referencia
    try:
        return _formato(codigo).rol == "referencia"
    except ValueError:
        return False


def es_local(codigo: str) -> bool:
    fuente_def = definicion(codigo)
    if fuente_def is not None:
        return fuente_def.es_local
    try:
        return _formato(codigo).es_local
    except ValueError:
        return False


def capacidades(codigo: str) -> frozenset[str]:
    fuente_def = definicion(codigo)
    if fuente_def is not None:
        return fuente_def.capacidades
    try:
        return _formato(codigo).capacidades
    except ValueError:
        return frozenset()


def etiqueta(codigo: str) -> str:
    fuente_def = definicion(codigo)
    if fuente_def is not None:
        return fuente_def.label
    try:
        return _formato(codigo).etiqueta
    except ValueError:
        return codigo


def etiquetas() -> dict[str, str]:
    salida = _etiquetas_formato()
    salida.update(fuentes_manifest.etiquetas())
    return salida


def fuentes_locales() -> list[Formato]:
    return _formatos_locales()


def default_primary() -> str:
    return fuentes_manifest.default_primary() or _default_primary_formato()


def nombre_archivo(codigo: str, inicio14: str, fin14: str) -> str:
    return fuente(codigo).archivo.format(inicio=inicio14, fin=fin14)


def nombre_no_publicados(codigo: str) -> str:
    return adaptador(codigo).archivo_no_publicados(codigo)


def nombre_atribucion(codigo: str) -> str:
    return adaptador(codigo).archivo_atribucion(codigo)


def nombre_informe_no_actualizados(codigo: str) -> str:
    return adaptador(codigo).archivo_no_actualizados(codigo)


def nombre_repetidos(codigo: str, sufijo: str) -> str:
    return adaptador(codigo).archivo_repetidos(codigo, sufijo)


def nombre_repetidos_final(codigo: str, sufijo: str) -> str:
    return adaptador(codigo).archivo_repetidos_final(codigo, sufijo)


def prefijo_compara(codigo: str) -> str:
    return fuente(codigo).prefijo_compara


__all__ = [
    "FUENTES",
    "REFERENCIA",
    "Fuente",
    "adaptador",
    "capacidades",
    "default_primary",
    "definicion",
    "es_local",
    "es_referencia",
    "etiqueta",
    "etiquetas",
    "formato",
    "fuente",
    "fuentes_locales",
    "locales",
    "nombre_archivo",
    "nombre_atribucion",
    "nombre_informe_no_actualizados",
    "nombre_no_publicados",
    "nombre_repetidos",
    "nombre_repetidos_final",
    "prefijo_compara",
    "referencia",
]
