"""Coincidencia y filtrado de eventos por código corto de analista."""

from __future__ import annotations

import re
import unicodedata

from flask import current_app, g, has_request_context

from ..domain.catalogs import manifest as fuentes_manifest
from ..extensions import db
from ..models import User

ROLES_RESTRINGIDOS = frozenset({"analista", "consulta"})
CAMPOS_ANALISTA = (
    "Analista",
    "analista",
    "Analista probable",
    "Analista_otra",
    "analista_otra",
)


def campos_analista() -> tuple[str, ...]:
    """Columnas de analista, incluidas las de cada fuente local del manifiesto."""
    extra = tuple(
        f"analista_{fuente.id}" for fuente in fuentes_manifest.locales()
    )
    return CAMPOS_ANALISTA + extra


def _prefijo_fuente() -> re.Pattern[str]:
    nombres = {"publicado", "local"}
    for fuente in fuentes_manifest.fuentes():
        nombres.add(fuente.id)
        nombres.add(fuente.label)
    patron = "|".join(re.escape(nombre) for nombre in sorted(nombres, key=len, reverse=True))
    return re.compile(rf"^\s*(?:{patron})\s*:\s*", re.IGNORECASE)


def normalizar_nombre(valor) -> str:
    """Normaliza mayúsculas, acentos, espacios y puntuación."""
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(caracter for caracter in texto if not unicodedata.combining(caracter))
    texto = texto.casefold()
    return re.sub(r"[^a-z0-9]+", "", texto)


def _nombres_texto(texto) -> list[str]:
    nombres = []
    prefijo = _prefijo_fuente()
    for parte in re.split(r"[;,]", str(texto or "")):
        limpio = prefijo.sub("", parte)
        normalizado = normalizar_nombre(limpio)
        if not normalizado or normalizado in {"sinnombre", "sin nombre"}:
            continue
        if normalizado not in nombres:
            nombres.append(normalizado)
    return nombres


def nombres_de_fila(fila: dict) -> list[str]:
    """Nombres de analista presentes en una fila, sin importar la columna."""
    nombres = []
    for clave in campos_analista():
        for nombre in _nombres_texto(fila.get(clave, "")):
            if nombre not in nombres:
                nombres.append(nombre)
    return nombres


def codigos_usuario(usuario) -> list[str]:
    """Código corto y alias normalizados del usuario."""
    if usuario is None:
        return []
    valores = [getattr(usuario, "analyst_code", "") or ""]
    valores.extend(
        re.split(r"[;,]", getattr(usuario, "analyst_aliases", "") or "")
    )
    codigos = []
    for valor in valores:
        codigo = normalizar_nombre(valor)
        if codigo and codigo not in codigos:
            codigos.append(codigo)
    return codigos


def usuario_restringido(usuario) -> bool:
    return getattr(usuario, "role", None) in ROLES_RESTRINGIDOS


def coincide(codigo: str, nombre: str) -> bool:
    """Igualdad o variante por prefijo de al menos 3 caracteres."""
    codigo = normalizar_nombre(codigo)
    nombre = normalizar_nombre(nombre)
    if not codigo or not nombre:
        return False
    if codigo == nombre:
        return True
    corto, largo = sorted((codigo, nombre), key=len)
    return (
        len(corto) >= 3
        and largo.startswith(corto)
        and len(largo) - len(corto) <= 2
    )


def _usuarios_codigos() -> list[tuple[int, list[str]]]:
    if has_request_context():
        cache = getattr(g, "_rcs_usuarios_codigos", None)
        if cache is not None:
            return cache
    usuarios = (
        db.session.execute(
            db.select(User).where(
                User.role.in_(ROLES_RESTRINGIDOS),
                User.active.is_(True),
            )
        )
        .scalars()
        .all()
    )
    datos = [
        (usuario.id, codigos_usuario(usuario))
        for usuario in usuarios
        if codigos_usuario(usuario)
    ]
    if has_request_context():
        g._rcs_usuarios_codigos = datos
    return datos


def evento_visible(fila: dict, usuario) -> bool:
    """True si el evento corresponde al analista, sin coincidencias ambiguas."""
    if not usuario_restringido(usuario):
        return True
    propios = set(codigos_usuario(usuario))
    if not propios:
        return False
    nombres = nombres_de_fila(fila)
    if not nombres:
        return False

    usuarios = _usuarios_codigos()
    for nombre in nombres:
        coincidentes = {
            user_id
            for user_id, codigos in usuarios
            if any(coincide(codigo, nombre) for codigo in codigos)
        }
        if len(coincidentes) > 1:
            if has_request_context():
                vistos = getattr(g, "_rcs_ambiguos", set())
                if nombre not in vistos:
                    current_app.logger.warning(
                        "Nombre de analista ambiguo: %s", nombre
                    )
                    vistos.add(nombre)
                    g._rcs_ambiguos = vistos
            continue
        if getattr(usuario, "id", None) in coincidentes:
            return True
    return False


def filtrar_filas(filas: list[dict], usuario) -> list[dict]:
    if not usuario_restringido(usuario):
        return filas
    return [fila for fila in filas if evento_visible(fila, usuario)]


__all__ = [
    "CAMPOS_ANALISTA",
    "ROLES_RESTRINGIDOS",
    "campos_analista",
    "codigos_usuario",
    "coincide",
    "evento_visible",
    "filtrar_filas",
    "nombres_de_fila",
    "normalizar_nombre",
    "usuario_restringido",
]
