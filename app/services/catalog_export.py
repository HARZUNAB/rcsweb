"""Catálogo sanitizado y mapas agregados para descarga."""

from __future__ import annotations

from pathlib import Path

from . import plots
from .analysts import CAMPOS_ANALISTA
from .results import exportar_filas, leer_todo

CAMPOS_CATALOGO = (
    ("Fecha_Hora", "Fecha y hora"),
    ("Latitud", "Latitud"),
    ("Longitud", "Longitud"),
    ("Prof.", "Prof. (km)"),
    ("Mag.", "Mag."),
    ("Tipo_mag.", "Tipo mag."),
    ("Referencia", "Referencia geográfica"),
)


def _campos_salida(columnas: list[str]) -> list[tuple[str, str]]:
    disponibles = set(columnas)
    campos = []
    for clave, titulo in CAMPOS_CATALOGO:
        if clave == "Referencia":
            if "Referencia" not in disponibles and "referencia" not in disponibles:
                continue
        if clave not in disponibles:
            continue
        campos.append((clave, titulo))
    return campos


def _valor(fila: dict, clave: str):
    if clave == "Referencia":
        return fila.get("Referencia") or fila.get("referencia", "")
    return fila.get(clave, "")


def preparar_catalogo(
    workspace: Path,
    archivo: str,
    opcion: str,
    *,
    q: str = "",
    filtros: dict[str, str] | None = None,
    sort: str = "",
    direccion: str = "asc",
    ocultar_analista: bool = False,
) -> dict:
    """CSV sanitizado, eventos y perfiles del catálogo filtrado."""
    ocultas = CAMPOS_ANALISTA if ocultar_analista else None
    filtros_limpios = {
        clave: valor
        for clave, valor in (filtros or {}).items()
        if not ocultas or clave not in ocultas
    }
    if ocultas and sort in ocultas:
        sort = ""
    columnas, filas = leer_todo(
        workspace,
        archivo,
        q=q,
        filtros=filtros_limpios,
        sort=sort,
        direccion=direccion,
        columnas_ocultas_busqueda=ocultas,
    )
    campos = _campos_salida(columnas)
    salida = [
        {titulo: _valor(fila, clave) for clave, titulo in campos}
        for fila in filas
    ]
    eventos = plots.eventos_catalogo(archivo, filas, opcion)
    perfiles = sorted(
        {
            evento.get("perfil")
            for evento in eventos
            if evento.get("perfil")
        }
    )
    return {
        "campos": [titulo for _clave, titulo in campos],
        "filas": salida,
        "eventos": eventos,
        "perfiles": perfiles,
        "total": len(salida),
    }


def csv_catalogo(datos: dict) -> bytes:
    return exportar_filas(datos["campos"], datos["filas"])


def resumen_mapa(titulo: str, total: int, filtros: str, job_id: str) -> dict:
    subtitulo = [f"Fuente: {titulo}", f"Eventos: {total}"]
    if filtros:
        subtitulo.append(filtros)
    return {
        "titulo": f"Catálogo {titulo}",
        "subtitulo": subtitulo,
        "filas": [],
        "nota": None,
        "pie": f"RCS Web · trabajo {job_id}",
    }


def mapa_planta(
    workspace: Path,
    datos: dict,
    opcion: str,
    *,
    cache_key: str,
    resumen: dict,
) -> bytes | None:
    if not datos["eventos"]:
        return None
    return plots.generar_mapa_grupo(
        workspace,
        datos["eventos"],
        opcion,
        resumen,
        cache_key + "|planta",
        modo="planta",
    )


def mapa_perfil(
    workspace: Path,
    datos: dict,
    opcion: str,
    perfil_id: str,
    *,
    cache_key: str,
    resumen: dict,
) -> bytes | None:
    eventos = [
        evento
        for evento in datos["eventos"]
        if evento.get("perfil") == perfil_id
    ]
    if not eventos:
        return None
    return plots.generar_mapa_grupo(
        workspace,
        eventos,
        opcion,
        resumen,
        cache_key + "|perfil|" + perfil_id,
        modo="auto",
    )


__all__ = [
    "CAMPOS_CATALOGO",
    "csv_catalogo",
    "mapa_perfil",
    "mapa_planta",
    "preparar_catalogo",
    "resumen_mapa",
]
