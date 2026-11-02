"""Manifiesto de fuentes de catálogo.

La lista de fuentes, sus nombres visibles y su rol viven en datos, no en el
código de la app. Un programa externo puede generar o reemplazar el manifiesto
junto con los catálogos canónicos.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

RUTA_POR_DEFECTO = Path(__file__).with_name("sources.json")


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
                str(extension).strip()
                for extension in item.get("accept", [])
                if str(extension).strip()
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
    referencias = [fuente for fuente in fuentes if fuente.es_referencia]
    if len(referencias) != 1:
        raise ValueError("El manifiesto debe tener exactamente una fuente de referencia.")
    if not any(fuente.es_local for fuente in fuentes):
        raise ValueError("El manifiesto debe incluir al menos una fuente local.")
    return tuple(fuentes)


def fuente_role(item: dict) -> str:
    return str(item.get("role") or "local")


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
    "aceptar",
    "cargar",
    "default_primary",
    "descargables",
    "etiqueta",
    "etiquetas",
    "fuentes",
    "locales",
    "opciones_locales",
    "por_id",
    "referencia",
]
