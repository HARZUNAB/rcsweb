"""Lectura de formularios con fuentes definidas por el manifiesto."""

from __future__ import annotations

from pathlib import Path

from flask import request

from ..domain.catalogs.manifest import Fuente


def opciones_formulario(
    fuentes: tuple[Fuente, ...],
    incluir_por_defecto: set[str] | None = None,
) -> list[dict]:
    incluidas = incluir_por_defecto or set()
    return [
        {
            "fuente": fuente,
            "incluir": fuente.id in incluidas,
            "alias": "",
            "archivo": None,
            "error": "",
        }
        for fuente in fuentes
    ]


def leer_formulario(fuentes: tuple[Fuente, ...]) -> list[dict]:
    opciones = []
    for fuente in fuentes:
        incluir = request.form.get(f"incluir_{fuente.id}", "").lower() in {
            "y",
            "yes",
            "on",
            "1",
            "true",
        }
        opciones.append(
            {
                "fuente": fuente,
                "incluir": incluir,
                "alias": (request.form.get(f"alias_{fuente.id}") or "").strip(),
                "archivo": request.files.get(fuente.id),
                "error": "",
            }
        )
    return opciones


def extension_permitida(fuente: Fuente, archivo) -> bool:
    if archivo is None or not getattr(archivo, "filename", ""):
        return False
    if not fuente.accept:
        return True
    sufijo = Path(archivo.filename).suffix.lower()
    aceptadas = {extension.lower() for extension in fuente.accept}
    return sufijo in aceptadas


def error_en(opciones: list[dict], fuente: Fuente, mensaje: str) -> None:
    for opcion in opciones:
        if opcion["fuente"].id == fuente.id:
            opcion["error"] = mensaje
            return


def fuente_por_id(opciones: list[dict], identificador: str) -> dict | None:
    return next(
        (opcion for opcion in opciones if opcion["fuente"].id == identificador),
        None,
    )


__all__ = [
    "error_en",
    "extension_permitida",
    "fuente_por_id",
    "leer_formulario",
    "opciones_formulario",
]
