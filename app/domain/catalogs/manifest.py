"""Manifiesto de fuentes de catálogo.

La lista de fuentes, sus nombres visibles y su rol viven en datos, no en el
código de la app. Un programa externo puede generar o reemplazar el manifiesto
junto con los catálogos canónicos.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .registry import existe as formato_existe

RUTA_POR_DEFECTO = Path(__file__).with_name("sources.json")
ID_VALIDO = re.compile(r"^[a-zA-Z0-9_-]+$")
HANDLERS_DESCARGA = {"eventquery", "seisan", "seiscomp"}
DISPONIBILIDADES = {"", "seiscomp"}


class ManifestError(ValueError):
    """Configuración de fuentes inválida."""

    def __init__(self, errores: list[str]):
        self.errores = list(errores)
        super().__init__("; ".join(self.errores))


@dataclass(frozen=True)
class Fuente:
    id: str
    label: str
    role: str
    format: str
    description: str = ""
    accept: tuple[str, ...] = ()
    validator: str = ""
    download_handler: str = ""
    stored_filename: str = ""
    requires_radius: bool = False
    availability: str = ""
    default_primary: bool = False
    visible_in_observaciones: bool = True

    @property
    def es_referencia(self) -> bool:
        return self.role == "reference"

    @property
    def es_local(self) -> bool:
        return self.role == "local"

    @property
    def descargable(self) -> bool:
        return bool(self.download_handler)

    @property
    def capacidades(self) -> frozenset[str]:
        from .registry import formato

        try:
            return formato(self.format).capacidades
        except ValueError:
            return frozenset()


def _ruta() -> Path:
    valor = os.environ.get("CATALOG_SOURCES_MANIFEST", "").strip()
    return Path(valor).expanduser() if valor else RUTA_POR_DEFECTO


@lru_cache(maxsize=8)
def _leer(ruta: str, _mtime: int) -> tuple[Fuente, ...]:
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    fuentes = []
    vistos = set()
    for item in datos.get("sources", []):
        fuente = Fuente(
            id=str(item["id"]).strip(),
            label=str(item.get("label") or item["id"]).strip(),
            role=str(item.get("role") or "local").strip(),
            format=str(item.get("format") or item["id"]).strip(),
            description=str(item.get("description") or "").strip(),
            accept=tuple(
                extension
                if extension.startswith(".")
                else "." + extension
                for extension in (
                    str(valor).strip()
                    for valor in item.get("accept", [])
                )
                if extension and extension != "."
            ),
            validator=str(item.get("validator") or item.get("format") or item["id"]).strip(),
            download_handler=str(item.get("download_handler") or "").strip(),
            stored_filename=str(item.get("stored_filename") or "").strip(),
            requires_radius=bool(item.get("requires_radius", False)),
            availability=str(item.get("availability") or "").strip(),
            default_primary=bool(item.get("default_primary", False)),
            visible_in_observaciones=bool(
                item.get("visible_in_observaciones", fuente_role(item) == "local")
            ),
        )
        if not fuente.id or fuente.id in vistos:
            raise ValueError(f"Fuente duplicada o vacía en el manifiesto: {fuente.id!r}")
        if fuente.role not in ("reference", "local"):
            raise ValueError(f"Rol inválido para {fuente.id}: {fuente.role!r}")
        vistos.add(fuente.id)
        fuentes.append(fuente)
    return tuple(fuentes)


def fuente_role(item: dict) -> str:
    return str(item.get("role") or "local")


def validar() -> tuple[Fuente, ...]:
    """Valida el manifiesto y devuelve sus fuentes.

    Se usa al arrancar la app y desde ``flask sources validate``. Un manifiesto
    inválido se rechaza completo para no dejar la aplicación en un estado
    ambiguo.
    """
    try:
        fuentes = cargar()
    except (OSError, ValueError) as exc:
        raise ManifestError([str(exc)]) from exc

    errores: list[str] = []
    if not fuentes:
        errores.append("El manifiesto no declara ninguna fuente.")
    referencias = [fuente for fuente in fuentes if fuente.es_referencia]
    if len(referencias) != 1:
        errores.append(
            "El manifiesto debe tener exactamente una fuente con role=reference."
        )
    if not any(fuente.es_local for fuente in fuentes):
        errores.append("El manifiesto debe incluir al menos una fuente local.")
    if sum(1 for fuente in fuentes if fuente.default_primary) > 1:
        errores.append("Solo una fuente puede tener default_primary=true.")

    from ...services import validators as modulo_validadores

    for fuente in fuentes:
        etiqueta = fuente.id or "(sin id)"
        if not fuente.id:
            errores.append("Hay una fuente sin id.")
        elif not ID_VALIDO.match(fuente.id):
            errores.append(
                f"El id {fuente.id!r} solo puede usar letras, números, guion y guion bajo."
            )
        if not fuente.label:
            errores.append(f"La fuente {etiqueta} no tiene label.")
        if not formato_existe(fuente.format):
            errores.append(
                f"La fuente {etiqueta} usa un formato desconocido: {fuente.format!r}."
            )
        if not hasattr(modulo_validadores, f"validar_{fuente.validator}"):
            errores.append(
                f"La fuente {etiqueta} usa un validador desconocido: "
                f"{fuente.validator!r}."
            )
        if fuente.download_handler and fuente.download_handler not in HANDLERS_DESCARGA:
            errores.append(
                f"La fuente {etiqueta} usa un handler de descarga desconocido: "
                f"{fuente.download_handler!r}."
            )
        if fuente.es_referencia and not fuente.download_handler:
            errores.append(
                f"La fuente de referencia {etiqueta} no tiene download_handler."
            )
        if fuente.availability not in DISPONIBILIDADES:
            errores.append(
                f"La fuente {etiqueta} usa una disponibilidad desconocida: "
                f"{fuente.availability!r}."
            )
        if fuente.es_referencia and fuente.default_primary:
            errores.append(
                f"La fuente de referencia {etiqueta} no puede ser default_primary."
            )
        if fuente.es_referencia and fuente.visible_in_observaciones:
            errores.append(
                f"La fuente de referencia {etiqueta} no puede aparecer en Resultados."
            )
        if fuente.stored_filename and (
            "/" in fuente.stored_filename or "\\" in fuente.stored_filename
        ):
            errores.append(
                f"La fuente {etiqueta} tiene un stored_filename con ruta: "
                f"{fuente.stored_filename!r}."
            )

    if errores:
        raise ManifestError(errores)
    return fuentes


def cargar() -> tuple[Fuente, ...]:
    ruta = _ruta()
    try:
        mtime = ruta.stat().st_mtime_ns
    except OSError as exc:
        raise RuntimeError(f"No se encontró el manifiesto de fuentes: {ruta}") from exc
    return _leer(str(ruta), mtime)


def fuentes() -> tuple[Fuente, ...]:
    return cargar()


def referencia() -> Fuente:
    return next(fuente for fuente in cargar() if fuente.es_referencia)


def locales() -> tuple[Fuente, ...]:
    return tuple(fuente for fuente in cargar() if fuente.es_local)


def descargables() -> tuple[Fuente, ...]:
    return tuple(fuente for fuente in locales() if fuente.descargable)


def por_id(identificador: str) -> Fuente | None:
    return next((fuente for fuente in cargar() if fuente.id == identificador), None)


def etiquetas() -> dict[str, str]:
    return {fuente.id: fuente.label for fuente in cargar()}


def formato_de(identificador: str) -> str:
    """Clave interna del formato de una fuente, o el propio id si no existe."""
    fuente = por_id(identificador)
    return fuente.format if fuente is not None else identificador


def capacidades(identificador: str) -> frozenset[str]:
    fuente = por_id(identificador)
    return fuente.capacidades if fuente is not None else frozenset()


def es_referencia(identificador: str) -> bool:
    fuente = por_id(identificador)
    return bool(fuente and fuente.es_referencia)


def es_local(identificador: str) -> bool:
    fuente = por_id(identificador)
    return bool(fuente and fuente.es_local)


def etiqueta(identificador: str) -> str:
    fuente = por_id(identificador)
    return fuente.label if fuente else identificador


def opciones_locales() -> list[tuple[str, str]]:
    return [(fuente.id, fuente.label) for fuente in locales()]


def default_primary() -> str:
    locales_disponibles = locales()
    for fuente in locales_disponibles:
        if fuente.default_primary:
            return fuente.id
    return locales_disponibles[0].id if locales_disponibles else ""


def aceptar(identificador: str) -> set[str]:
    fuente = por_id(identificador)
    return set(fuente.accept) if fuente else set()


__all__ = [
    "Fuente",
    "ManifestError",
    "aceptar",
    "cargar",
    "default_primary",
    "descargables",
    "capacidades",
    "es_local",
    "es_referencia",
    "etiqueta",
    "etiquetas",
    "formato_de",
    "fuentes",
    "locales",
    "opciones_locales",
    "por_id",
    "referencia",
    "validar",
]
