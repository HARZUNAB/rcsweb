"""Catálogo sanitizado y mapas agregados para descarga."""

from __future__ import annotations

from pathlib import Path

from . import panels, plots, ubicacion
from .analysts import CAMPOS_ANALISTA
from .results import exportar_filas, leer_todo

PLANTAS = (
    ("nacional", "Chile continental", "Nacional"),
    ("insular", "Territorio insular", "Insular"),
    ("antartico", "Territorio antártico", "Antártico"),
    ("otros", "Otros", None),
)

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


def _radio_influencia(mag) -> float:
    """Radio de influencia en km según magnitud."""
    try:
        valor = float(str(mag).strip())
    except (TypeError, ValueError):
        return 200.0
    if valor < 4.0:
        return 200.0
    if valor < 5.0:
        return 300.0
    if valor < 6.0:
        return 400.0
    return 500.0


def _categoria_planta(evento: dict) -> str:
    territorio = evento.get("territorio") or "Otros"
    if territorio != "Otros":
        return territorio
    distancia = ubicacion.distancia_chile_km(evento["lat"], evento["lon"])
    radio = _radio_influencia(evento.get("mag"))
    if distancia is None or distancia <= radio:
        return "Nacional"
    return "Otros"


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
    for evento in eventos:
        evento.setdefault("lat", evento.get("latitud"))
        evento.setdefault("lon", evento.get("longitud"))
    panels.categorizar_territorio(eventos)
    for evento in eventos:
        evento["territorio"] = _categoria_planta(evento)
    perfiles = sorted(
        {
            evento.get("perfil")
            for evento in eventos
            if evento.get("perfil")
        }
    )
    plantas = []
    for clave, titulo, territorio in PLANTAS:
        categoria = "Otros" if territorio is None else territorio
        eventos_planta = [
            evento
            for evento in eventos
            if evento.get("territorio") == categoria
        ]
        if eventos_planta:
            plantas.append(
                {
                    "clave": clave,
                    "titulo": titulo,
                    "territorio": territorio,
                    "eventos": eventos_planta,
                    "total": len(eventos_planta),
                }
            )
    return {
        "campos": [titulo for _clave, titulo in campos],
        "filas": salida,
        "eventos": eventos,
        "perfiles": perfiles,
        "plantas": plantas,
        "total": len(salida),
    }


def csv_catalogo(datos: dict) -> bytes:
    return exportar_filas(datos["campos"], datos["filas"])


def resumen_mapa(
    titulo: str,
    total: int,
    filtros: str,
    job_id: str,
    mapa: str = "",
) -> dict:
    subtitulo = [f"Fuente: {titulo}", f"Eventos: {total}"]
    if mapa:
        subtitulo.insert(0, f"Mapa: {mapa}")
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
    planta: dict,
    opcion: str,
    *,
    cache_key: str,
    resumen: dict,
) -> bytes | None:
    if not planta["eventos"]:
        return None
    return plots.generar_mapa_grupo(
        workspace,
        planta["eventos"],
        opcion,
        resumen,
        cache_key + "|planta|" + planta["clave"],
        modo="planta",
        territorio=planta["territorio"],
    )


def mapa_perfil(
    workspace: Path,
    datos: dict,
    opcion: str,
    perfil_id: str,
    *,
    cache_key: str,
    resumen: dict,
    modo: str = "auto",
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
        cache_key + "|perfil|" + perfil_id + "|" + modo,
        modo=modo,
    )


__all__ = [
    "CAMPOS_CATALOGO",
    "csv_catalogo",
    "mapa_perfil",
    "mapa_planta",
    "preparar_catalogo",
    "resumen_mapa",
]
