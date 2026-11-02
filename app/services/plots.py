"""Mapas y miniaturas de perfil.

Los mapas completos se renderizan en un subproceso con ``plotear.py`` del core
en modo ``Agg`` (sin Tk) y se cachean como PNG dentro del workspace. Las
miniaturas se dibujan en proceso con matplotlib puro: son livianas y no
necesitan cartopy.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import subprocess
import sys
import threading
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from flask import current_app  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from . import colores
from .borders import texto_frontera_coords  # noqa: E402
from .detail import (  # noqa: E402
    COLORES_FUENTE,
    ETIQUETAS_FUENTE,
    distancia_km,
    grupo_repetidos,
)

_LOCK = threading.RLock()
_PERFILES = None
_PERFILES_CORE = None

COLORES = {
    "local": "#ffd400",
    "publicado": "#d63384",
    "seleccionado": "#d62728",
    None: "#1f77b4",
}


def _core() -> Path:
    return Path(current_app.config["RCS_CORE_PATH"]).resolve()


def _preparar_core() -> Path:
    core = _core()
    if core.is_dir() and str(core) not in sys.path:
        sys.path.insert(0, str(core))
    return core


def _perfiles():
    global _PERFILES, _PERFILES_CORE
    core = _core()
    if _PERFILES is None or _PERFILES_CORE != core:
        _preparar_core()
        import asigna_perfiles as ap  # type: ignore

        _PERFILES = ap.detectar_perfiles()
        _PERFILES_CORE = core
    return _PERFILES or []


def _numero(valor):
    if valor is None:
        return None
    texto = str(valor).strip()
    if not texto:
        return None
    try:
        return float(texto)
    except ValueError:
        return None


def _evento_con_claves(
    fila: dict,
    claves: dict,
    rol: str | None = None,
    percibido: str = "",
) -> dict:
    return {
        "rol": rol,
        "percibido": percibido,
        "fecha hora": fila.get(claves["fecha"], ""),
        "latitud": _numero(fila.get(claves["lat"])),
        "longitud": _numero(fila.get(claves["lon"])),
        "prof": _numero(fila.get(claves["prof"])),
        "magnitud": fila.get(claves["mag"], ""),
        "tipo": fila.get(claves["tipo"], ""),
        "analista": fila.get(claves.get("analista", ""), ""),
    }


def _eventos(tabla: str, archivo: str, filas: list[dict], indice: int) -> list[dict]:
    if indice < 0 or indice >= len(filas):
        return []
    fila = filas[indice]

    if tabla == "no_actualizados":
        eventos = [
            _evento_con_claves(
                fila,
                {
                    "fecha": "fecha_local",
                    "lat": "lat_local",
                    "lon": "lon_local",
                    "prof": "prof_local",
                    "mag": "mag_local",
                    "tipo": "tipo_mag_local",
                    "analista": "analista",
                },
                rol="local",
            ),
            _evento_con_claves(
                fila,
                {
                    "fecha": "fecha_eventquery",
                    "lat": "lat_eventquery",
                    "lon": "lon_eventquery",
                    "prof": "prof_eventquery",
                    "mag": "mag_eventquery",
                    "tipo": "tipo_mag_eventquery",
                },
                rol="publicado",
            ),
        ]
        return [evento for evento in eventos if evento["latitud"] is not None]

    if tabla in ("no_publicados", "catalogos"):
        evento = _evento_con_claves(
            fila,
            {
                "fecha": "Fecha_Hora",
                "lat": "Latitud",
                "lon": "Longitud",
                "prof": "Prof.",
                "mag": "Mag.",
                "tipo": "Tipo_mag.",
                "analista": "Analista",
            },
            rol="local",
            percibido=fila.get("Percep.", ""),
        )
        return [evento] if evento["latitud"] is not None else []

    grupo = grupo_repetidos(filas, indice, archivo)
    if not grupo:
        return []
    grupo.sort(key=lambda item: 0 if item.get("_fila") == indice else 1)
    eventos = []
    for item in grupo:
        evento = _evento_con_claves(
            item["fila"],
            {
                "fecha": "fecha_hora",
                "lat": "latitud",
                "lon": "longitud",
                "prof": "prof",
                "mag": "mag",
                "tipo": "tipomag",
                "analista": "analista",
            },
            rol="seleccionado" if item.get("_fila") == indice else None,
            percibido=item["fila"].get("percibido", ""),
        )
        if evento["latitud"] is None:
            continue
        if not evento["analista"]:
            evento["analista"] = (
                item["fila"].get("analista_seisan") or item["fila"].get("analista_seiscomp") or ""
            )
        eventos.append(evento)
    return eventos


def _asignar(eventos: list[dict], perfiles):
    if not perfiles:
        return eventos, None
    _preparar_core()
    import asigna_perfiles as ap  # type: ignore

    validos = [evento for evento in eventos if evento.get("latitud") is not None]
    if not validos:
        return eventos, None

    referencia = next((evento for evento in validos if evento.get("rol") == "local"), validos[0])
    perfil = None
    for candidato in [referencia] + [e for e in validos if e is not referencia]:
        try:
            datos = ap.asignar_perfil_evento(
                candidato["longitud"],
                candidato["latitud"],
                candidato.get("prof"),
                perfiles,
            )
        except Exception:
            continue
        perfil_id = datos.get("perfil")
        if not perfil_id:
            continue
        candidato.update(datos)
        perfil = next((p for p in perfiles if p.get("id") == perfil_id), None)
        referencia = candidato
        if perfil is not None:
            break

    if perfil is None:
        return eventos, None

    for evento in validos:
        if evento is referencia:
            continue
        try:
            perp, along = ap.distancia_al_perfil(evento["longitud"], evento["latitud"], perfil)
            evento["perfil"] = perfil["id"]
            evento["along_km"] = along
            evento["perp_km"] = perp
        except Exception:
            continue
    return eventos, perfil


def _fuente(tabla: str, opcion: str) -> str:
    if tabla in ("no_publicados", "no_actualizados", "catalogos"):
        return opcion
    if opcion.startswith("publica"):
        return "eventquery"
    if opcion.startswith("seiscomp"):
        return "seiscomp"
    return "seisan"


def _ruta_cache(
    workspace: Path,
    carpeta: str,
    tabla: str,
    archivo: str,
    indice: int,
    sufijo: str = "",
) -> Path:
    raiz = workspace.resolve()
    nombre = Path(archivo).name
    if nombre != archivo:
        raise ValueError("nombre de archivo inválido")
    base = (raiz / "plots" / carpeta / tabla / Path(nombre).stem).resolve()
    if not base.is_relative_to(raiz):
        raise ValueError("ruta fuera del workspace")
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{indice}{sufijo}.png"


def _placeholder(mensaje: str, ancho: int = 1200, alto: int = 520) -> bytes:
    imagen = Image.new("RGB", (ancho, alto), "#f3f5f7")
    dibujo = ImageDraw.Draw(imagen)
    dibujo.text(
        (ancho // 2, alto // 2),
        mensaje,
        fill="#6c757d",
        anchor="mm",
        align="center",
    )
    buffer = io.BytesIO()
    imagen.save(buffer, format="PNG")
    return buffer.getvalue()


def _serie(valores) -> list:
    if valores is None:
        return []
    resultado = []
    for valor in valores:
        try:
            numero = float(valor)
        except (TypeError, ValueError):
            resultado.append(None)
            continue
        resultado.append(numero if math.isfinite(numero) else None)
    return resultado


def _residuo_slab(evento: dict, perfil) -> float | None:
    if perfil is None or evento.get("along_km") is None or evento.get("prof") is None:
        return None
    try:
        _preparar_core()
        import asigna_perfiles as ap  # type: ignore

        slab = ap.profundidad_slab_en(perfil, float(evento["along_km"]))
        slab = float(slab)
        if not math.isfinite(slab):
            return None
        return abs(float(evento["prof"]) - slab)
    except Exception:
        return None


def _es_sospechoso(evento: dict) -> bool:
    try:
        _preparar_core()
        import sismicidad  # type: ignore

        return bool(sismicidad.es_sospechoso(evento))
    except Exception:
        return False


def clasificar_eventos(
    tabla: str, archivo: str, filas: list[dict], indice: int
) -> tuple[list[dict], dict | None]:
    """Eventos con perfil, residuo al slab y clasificación de sospechoso."""
    eventos = _eventos(tabla, archivo, filas, indice)
    if not eventos:
        return [], None
    try:
        eventos, perfil = _asignar(eventos, _perfiles())
    except Exception:
        perfil = None
    for evento in eventos:
        evento["residuo_km"] = _residuo_slab(evento, perfil)
        evento["sospechoso"] = _es_sospechoso(evento)
    return eventos, perfil


def marcar_sospechosos(puntos: list[dict], eventos: list[dict]) -> list[dict]:
    """Propaga la clasificación de los eventos a los puntos del mapa."""
    indice = {}
    for evento in eventos:
        try:
            clave = (
                round(float(evento["latitud"]), 6),
                round(float(evento["longitud"]), 6),
            )
        except (KeyError, TypeError, ValueError):
            continue
        indice[clave] = indice.get(clave, False) or bool(evento.get("sospechoso"))
    for punto in puntos:
        try:
            clave = (round(float(punto["lat"]), 6), round(float(punto["lon"]), 6))
        except (KeyError, TypeError, ValueError):
            punto["sospechoso"] = False
            continue
        punto["sospechoso"] = indice.get(clave, False)
    return puntos


def perfil_desde_eventos(eventos: list[dict], perfil, opcion: str, tabla: str):
    if perfil is None or not eventos:
        return None
    referencia = next(
        (evento for evento in eventos if evento.get("rol") in ("local", "seleccionado")),
        eventos[0],
    )
    puntos = []
    for evento in eventos:
        along = evento.get("along_km")
        profundidad = evento.get("prof")
        if along is None or profundidad is None:
            continue
        if tabla == "no_actualizados":
            fuente = opcion if evento.get("rol") == "local" else "eventquery"
        elif tabla == "no_publicados":
            fuente = opcion
        else:
            fuente = _fuente(tabla, opcion)
        # Mismos colores que el detalle: rol local/publicado y percepción.
        codigo = fuente if fuente in COLORES_FUENTE else "publicado"
        estilo = colores.estilo_punto(codigo, evento)
        lat = evento.get("latitud")
        lon = evento.get("longitud")
        distancia = distancia_km(
            referencia.get("latitud"),
            referencia.get("longitud"),
            lat,
            lon,
        )
        puntos.append(
            {
                "fuente": codigo,
                "etiqueta": ETIQUETAS_FUENTE[codigo],
                "color": estilo["color"],
                "borde": estilo["borde"],
                "borde_ancho": estilo["borde_ancho"],
                "rol": evento.get("rol"),
                "percibido": evento.get("percibido", ""),
                "fecha": evento.get("fecha hora", ""),
                "lat": lat,
                "lon": lon,
                "prof": float(profundidad),
                "along_km": float(along),
                "perp_km": evento.get("perp_km"),
                "dist_km": None if distancia is None else round(distancia, 1),
                "mag": evento.get("magnitud", ""),
                "tipo": evento.get("tipo", ""),
                "analista": evento.get("analista", ""),
                "frontera": texto_frontera_coords(lat, lon),
                "sospechoso": bool(evento.get("sospechoso")),
                "residuo_km": evento.get("residuo_km"),
                "estado": "",
            }
        )
    slab = perfil.get("slab") or {}
    return {
        "id": perfil.get("id", ""),
        "topo_p": _serie(perfil.get("topo_p")),
        "topo_alt": _serie(perfil.get("topo_alt")),
        "slab_lon": _serie(slab.get("lon")),
        "slab_lat": _serie(slab.get("lat")),
        "slab_p": _serie(slab.get("p")),
        "slab_depth": _serie(slab.get("depth")),
        "eventos": puntos,
    }


def perfil_mapa(
    tabla: str, archivo: str, filas: list[dict], indice: int, opcion: str
) -> dict | None:
    """Perfil con topografía, slab y eventos para el detalle interactivo."""
    eventos, perfil = clasificar_eventos(tabla, archivo, filas, indice)
    return perfil_desde_eventos(eventos, perfil, opcion, tabla)


def _dibujar_miniatura(eventos: list[dict], perfil) -> bytes:
    if perfil is None:
        return _placeholder("Sin perfil", ancho=260, alto=110)

    topo_p = perfil.get("topo_p")
    topo_alt = perfil.get("topo_alt")
    slab = perfil.get("slab") or {}

    figura, eje = plt.subplots(figsize=(2.6, 1.1), dpi=100)
    figura.patch.set_facecolor("#f6f7f9")
    eje.set_facecolor("#f6f7f9")

    try:
        if topo_p is not None and topo_alt is not None and len(topo_p) == len(topo_alt):
            eje.fill_between(
                topo_p,
                0,
                topo_alt / 1000.0,
                color="#e8dcc2",
                linewidth=0,
                zorder=1,
            )
    except Exception:
        pass

    profundidades = []
    try:
        p = slab.get("p")
        d = slab.get("depth")
        if p is not None and d is not None and len(p) == len(d):
            eje.plot(p, d, color="#1f1f1f", linewidth=1.2, zorder=2)
            profundidades.extend(float(v) for v in d if v == v)
    except Exception:
        pass

    for evento in eventos:
        profundidad = evento.get("prof")
        along = evento.get("along_km")
        if profundidad is None or along is None:
            continue
        profundidades.append(float(profundidad))
        eje.scatter(
            along,
            profundidad,
            s=24,
            c=COLORES.get(evento.get("rol"), COLORES[None]),
            edgecolors="#111111",
            linewidths=0.5,
            zorder=5,
        )

    if topo_p is not None and len(topo_p):
        eje.set_xlim(0, float(max(topo_p)))
    maximo = max(profundidades + [100.0]) * 1.08
    eje.set_ylim(maximo, -5)
    eje.set_xticks([])
    eje.set_yticks([])
    for borde in eje.spines.values():
        borde.set_visible(False)
    eje.set_title(perfil.get("id", ""), fontsize=6, pad=1, color="#495057")

    figura.tight_layout(pad=0.15)
    buffer = io.BytesIO()
    figura.savefig(buffer, format="png", facecolor=figura.get_facecolor())
    plt.close(figura)
    return buffer.getvalue()


def generar_miniatura(
    workspace: Path,
    tabla: str,
    archivo: str,
    filas: list[dict],
    indice: int,
) -> bytes:
    """Miniatura del perfil de una fila, cacheada en el workspace."""
    destino = _ruta_cache(workspace, "miniaturas", tabla, archivo, indice)
    if destino.is_file():
        return destino.read_bytes()

    with _LOCK:
        if destino.is_file():
            return destino.read_bytes()
        try:
            eventos = _eventos(tabla, archivo, filas, indice)
            if not eventos:
                png = _placeholder("Sin perfil", ancho=260, alto=110)
            else:
                _, perfil = _asignar(eventos, _perfiles())
                png = _dibujar_miniatura(eventos, perfil)
        except Exception:
            current_app.logger.exception("No se pudo generar la miniatura")
            png = _placeholder("Sin perfil", ancho=260, alto=110)

    temporal = destino.with_suffix(".tmp.png")
    temporal.write_bytes(png)
    temporal.replace(destino)
    return png


def _valor_fila(fila: dict, *claves: str) -> str:
    for clave in claves:
        valor = fila.get(clave)
        if valor is not None and str(valor).strip():
            return str(valor).strip()
    return "—"


def _texto_mag(fila: dict, mag: str, tipo: str) -> str:
    valor = _valor_fila(fila, mag)
    clase = _valor_fila(fila, tipo)
    return f"{valor} {clase}" if clase != "—" else valor


def _frontera_evento(fila: dict, lat: str, lon: str) -> str:
    try:
        return texto_frontera_coords(float(fila.get(lat)), float(fila.get(lon)))
    except (TypeError, ValueError):
        return "—"


def _fila_evento(
    fecha: str,
    magnitud: str,
    profundidad: str,
    latitud: str,
    longitud: str,
    analista: str = "",
    extras: list[str] | None = None,
) -> str:
    """Una fila compacta con los parámetros de un evento."""
    prof = str(profundidad).strip() if profundidad is not None else "—"
    partes = [
        fecha or "—",
        magnitud or "—",
        f"{prof} km" if prof and prof != "—" else "—",
        f"{latitud}, {longitud}",
    ]
    if analista and analista != "—":
        partes.append(str(analista))
    for extra in extras or []:
        if extra:
            partes.append(str(extra))
    return " | ".join(partes)


def _analista_repetido(fila: dict) -> str:
    for clave in ("analista", "analista_seisan", "analista_seiscomp"):
        valor = str(fila.get(clave) or "").strip()
        if valor:
            return valor
    return "—"


def _nota_no_actualizado(fila: dict) -> str | None:
    partes = []
    dt = _valor_fila(fila, "dt_seg")
    if dt != "—":
        partes.append(f"Δt {dt} s")
    dlat = _valor_fila(fila, "dlat")
    dlon = _valor_fila(fila, "dlon")
    if dlat != "—" or dlon != "—":
        partes.append(f"Δ {dlat}°, {dlon}°")
    dist = _valor_fila(fila, "dist_km")
    if dist != "—":
        partes.append(f"Dist. {dist} km")
    estado = _valor_fila(fila, "publicacion_probable")
    if estado != "—":
        partes.append(f"Estado: {estado}")
    revision = _valor_fila(fila, "revision")
    if revision != "—":
        partes.append(f"Revisión: {revision}")
    discrepancias = _valor_fila(fila, "discrepancias")
    if discrepancias != "—":
        partes.append(f"Discrepancias: {discrepancias}")
    frontera = _frontera_evento(fila, "lat_local", "lon_local")
    if frontera != "—":
        partes.append(f"Frontera: {frontera}")
    return " | ".join(partes) or None


def _filas_evento(
    tabla: str, filas: list[dict], indice: int, archivo: str
) -> tuple[list[str], str | None]:
    """Una fila por evento para el encabezado del PNG.

    Los no actualizados llevan dos filas (local y publicado) y una nota con la
    diferencia. Los repetidos llevan una fila por solución del grupo.
    """
    fila = filas[indice]

    if tabla == "no_actualizados":
        local = _fila_evento(
            _valor_fila(fila, "fecha_local"),
            _texto_mag(fila, "mag_local", "tipo_mag_local"),
            _valor_fila(fila, "prof_local"),
            _valor_fila(fila, "lat_local"),
            _valor_fila(fila, "lon_local"),
            _valor_fila(fila, "analista"),
        )
        publicado = _fila_evento(
            _valor_fila(fila, "fecha_eventquery"),
            _texto_mag(fila, "mag_eventquery", "tipo_mag_eventquery"),
            _valor_fila(fila, "prof_eventquery"),
            _valor_fila(fila, "lat_eventquery"),
            _valor_fila(fila, "lon_eventquery"),
        )
        return [f"Local · {local}", f"Publicado · {publicado}"], _nota_no_actualizado(fila)

    if tabla == "repetidos":
        try:
            grupo = grupo_repetidos(filas, indice, archivo)
        except Exception:
            grupo = []
        if not grupo:
            grupo = [{"fila": fila, "_fila": indice}]
        grupo.sort(key=lambda item: 0 if item.get("_fila", indice) == indice else 1)
        filas_evento = []
        for item in grupo:
            actual = item.get("fila", fila)
            seleccionado = item.get("_fila", indice) == indice
            etiqueta = "Seleccionado" if seleccionado else "Solución"
            extras = []
            referencia = _valor_fila(actual, "referencia")
            if referencia != "—":
                extras.append(f"Referencia: {referencia}")
            percibido = _valor_fila(actual, "percibido")
            if percibido != "—":
                extras.append(f"Percibido: {percibido}")
            texto = _fila_evento(
                _valor_fila(actual, "fecha_hora"),
                _texto_mag(actual, "mag", "tipomag"),
                _valor_fila(actual, "prof"),
                _valor_fila(actual, "latitud"),
                _valor_fila(actual, "longitud"),
                _analista_repetido(actual),
                extras,
            )
            filas_evento.append(f"{etiqueta} · {texto}")
        nota = []
        if len(grupo) > 1:
            nota.append(f"Grupo: {len(grupo)} soluciones")
        frontera = _frontera_evento(fila, "latitud", "longitud")
        if frontera != "—":
            nota.append(f"Frontera: {frontera}")
        return filas_evento, " | ".join(nota) or None

    # No publicados y catálogos de entrada.
    extras = []
    publicado = _valor_fila(fila, "Publicado_en")
    if publicado != "—":
        extras.append(f"Publicado en: {publicado}")
    estado = _valor_fila(fila, "Estado")
    if estado != "—":
        extras.append(f"Estado: {estado}")
    referencia = _valor_fila(fila, "Referencia")
    if referencia != "—":
        extras.append(f"Referencia: {referencia}")
    percibido = _valor_fila(fila, "Percib.", "Percibido")
    if percibido != "—":
        extras.append(f"Percibido: {percibido}")
    frontera = _frontera_evento(fila, "Latitud", "Longitud")
    if frontera != "—":
        extras.append(f"Frontera: {frontera}")
    texto = _fila_evento(
        _valor_fila(fila, "Fecha_Hora"),
        _texto_mag(fila, "Mag.", "Tipo_mag."),
        _valor_fila(fila, "Prof."),
        _valor_fila(fila, "Latitud"),
        _valor_fila(fila, "Longitud"),
        _valor_fila(fila, "Analista", "Analista probable"),
        extras,
    )
    return [texto], None


def resumen_mapa(
    tabla: str,
    titulo: str,
    filas: list[dict],
    indice: int,
    archivo: str,
    job_id: str,
) -> dict | None:
    """Datos que se dibujan en el encabezado del PNG del evento."""
    if indice < 0 or indice >= len(filas):
        return None
    filas_evento, nota = _filas_evento(tabla, filas, indice, archivo)
    return {
        "titulo": titulo,
        "subtitulo": [],
        "filas": filas_evento,
        "nota": nota,
        "pie": f"RCS Web · trabajo {job_id}",
    }


def _envolver(texto: str, fuente, ancho: float, dibujo: ImageDraw.ImageDraw):
    lineas = []
    for bloque in str(texto).split("\n"):
        actual = ""
        for palabra in bloque.split():
            candidato = (actual + " " + palabra).strip()
            if not actual or dibujo.textlength(candidato, font=fuente) <= ancho:
                actual = candidato
            else:
                lineas.append(actual)
                actual = palabra
        lineas.append(actual)
    return lineas or [""]


def _fuente_imagen(nombre: str, tamano: int):
    try:
        ruta = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / nombre
        return ImageFont.truetype(str(ruta), tamano)
    except Exception:
        return ImageFont.load_default()


def _lista_texto(valor) -> list[str]:
    if not valor:
        return []
    if isinstance(valor, (list, tuple)):
        return [str(item) for item in valor if str(item).strip()]
    return [str(valor)]


def _ajustar_fuente(filas: list[str], disponible: float, dibujo: ImageDraw.ImageDraw):
    """Fuente común para las filas: 22 px, reduciendo hasta 16 si no caben."""
    for tamano in range(22, 15, -1):
        fuente = _fuente_imagen("DejaVuSans.ttf", tamano)
        if all(dibujo.textlength(fila, font=fuente) <= disponible for fila in filas):
            return fuente, tamano
    return _fuente_imagen("DejaVuSans.ttf", 16), 16


def _recortar(
    texto: str, fuente, ancho: float, dibujo: ImageDraw.ImageDraw
) -> str:
    """Recorta con puntos suspensivos si una fila excede el ancho."""
    if dibujo.textlength(texto, font=fuente) <= ancho:
        return texto
    puntos = "…"
    bajo, alto = 0, len(texto)
    while bajo < alto:
        medio = (bajo + alto + 1) // 2
        if dibujo.textlength(texto[:medio] + puntos, font=fuente) <= ancho:
            bajo = medio
        else:
            alto = medio - 1
    return texto[:bajo].rstrip() + puntos


def _componer_resumen(png: bytes, resumen: dict | None) -> bytes:
    """Agrega el encabezado con los datos del evento o del grupo al PNG."""
    if not resumen:
        return png
    try:
        original = Image.open(io.BytesIO(png)).convert("RGB")
    except Exception:
        return png

    ancho, alto = original.size
    margen = 30
    disponible = ancho - 2 * margen
    fuente_titulo = _fuente_imagen("DejaVuSans-Bold.ttf", 30)
    fuente_subtitulo = _fuente_imagen("DejaVuSans.ttf", 18)
    fuente_nota = _fuente_imagen("DejaVuSans.ttf", 16)
    fuente_pie = _fuente_imagen("DejaVuSans.ttf", 13)
    dibujo = ImageDraw.Draw(original)

    titulo = _envolver(resumen.get("titulo", ""), fuente_titulo, disponible, dibujo)
    subtitulo = []
    for linea in _lista_texto(resumen.get("subtitulo")):
        subtitulo.extend(
            _envolver(linea, fuente_subtitulo, disponible, dibujo)
        )
    filas = [str(fila) for fila in resumen.get("filas", []) if str(fila).strip()]
    fuente_filas, tamano_filas = _ajustar_fuente(filas, disponible, dibujo)
    filas = [
        _recortar(fila, fuente_filas, disponible, dibujo) for fila in filas
    ]
    nota = []
    if resumen.get("nota"):
        nota = _envolver(
            resumen["nota"], fuente_nota, disponible, dibujo
        )
    pie = resumen.get("pie", "")

    alto_titulo = 37
    alto_subtitulo = 26
    alto_fila = tamano_filas + 9
    alto_nota = 22
    alto_pie = 20
    encabezado = margen
    encabezado += alto_titulo * len(titulo)
    encabezado += 4 + 12
    encabezado += alto_subtitulo * len(subtitulo)
    if subtitulo:
        encabezado += 8
    encabezado += alto_fila * len(filas)
    if filas:
        encabezado += 6
    encabezado += alto_nota * len(nota)
    if nota:
        encabezado += 6
    encabezado += alto_pie + margen

    nueva = Image.new("RGB", (ancho, encabezado + alto), "#f4f7fb")
    nueva.paste(original, (0, encabezado))
    dibujo = ImageDraw.Draw(nueva)

    y = margen
    for linea in titulo:
        dibujo.text((margen, y), linea, font=fuente_titulo, fill="#1f3a5f")
        y += alto_titulo
    y += 4
    dibujo.line((margen, y, ancho - margen, y), fill="#dbe4ee", width=2)
    y += 12
    for linea in subtitulo:
        dibujo.text((margen, y), linea, font=fuente_subtitulo, fill="#34495e")
        y += alto_subtitulo
    if subtitulo:
        y += 8
    for linea in filas:
        dibujo.text((margen, y), linea, font=fuente_filas, fill="#1f2933")
        y += alto_fila
    if filas:
        y += 6
    for linea in nota:
        dibujo.text((margen, y), linea, font=fuente_nota, fill="#52606d")
        y += alto_nota
    if nota:
        y += 6
    if pie:
        dibujo.text((margen, y), pie, font=fuente_pie, fill="#7b8794")

    buffer = io.BytesIO()
    nueva.save(buffer, format="PNG")
    return buffer.getvalue()


def _renderizar_core(
    workspace: Path,
    destino: Path,
    eventos: list[dict],
    fuente: str,
    resumen: dict | None,
    modo: str = "auto",
) -> bytes:
    """Ejecuta el renderizador del core y compone el encabezado."""
    if destino.is_file():
        return destino.read_bytes()

    with _LOCK:
        if destino.is_file():
            return destino.read_bytes()

        try:
            core = _preparar_core()
            if not core.is_dir():
                raise ValueError("el core del proyecto no está montado")
            if not eventos:
                raise ValueError("el grupo no tiene eventos con coordenadas")

            cli = Path(__file__).with_name("plot_cli.py")
            entorno = os.environ.copy()
            entorno["RCS_CORE_PATH"] = str(core)
            entorno["MPLBACKEND"] = "Agg"
            entorno["PYTHONPATH"] = os.pathsep.join(
                parte for parte in (str(core), entorno.get("PYTHONPATH", "")) if parte
            )

            temporal = destino.with_suffix(".tmp.png")
            proceso = subprocess.run(
                [sys.executable, str(cli), str(temporal)],
                input=json.dumps(
                    {
                        "eventos": eventos,
                        "fuente": fuente,
                        "modo": modo,
                    },
                    ensure_ascii=False,
                ),
                cwd=str(workspace),
                env=entorno,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            if proceso.returncode != 0 or not temporal.is_file():
                detalle = (proceso.stderr or proceso.stdout or "").strip()[-1500:]
                raise RuntimeError(detalle or "el renderizador no generó la imagen")
            final = _componer_resumen(temporal.read_bytes(), resumen)
            destino.write_bytes(final)
            temporal.unlink(missing_ok=True)
            return final
        except Exception as exc:
            current_app.logger.warning("No se pudo generar el mapa: %s", exc)
            # No se cachea el error: el próximo pedido puede reintentar.
            return _componer_resumen(
                _placeholder(
                    f"Mapa no disponible\n{str(exc)[:160]}",
                    ancho=1200,
                    alto=520,
                ),
                resumen,
            )


def generar_mapa(
    workspace: Path,
    tabla: str,
    opcion: str,
    archivo: str,
    filas: list[dict],
    indice: int,
    resumen: dict | None = None,
) -> bytes:
    """Mapa completo (planta + perfil) con resumen del evento en el PNG."""
    destino = _ruta_cache(
        workspace, "mapas", tabla, archivo, indice, sufijo="_resumen"
    )
    eventos = _eventos(tabla, archivo, filas, indice)
    return _renderizar_core(
        workspace,
        destino,
        eventos,
        _fuente(tabla, opcion),
        resumen,
    )


def generar_mapa_grupo(
    workspace: Path,
    eventos: list[dict],
    fuente: str,
    resumen: dict | None,
    cache_key: str,
    modo: str = "auto",
) -> bytes:
    """Mapa de un grupo de Paneles, sin listado de eventos en el PNG.

    ``modo='auto'`` deja que el core elija planta + perfil; ``modo='planta'``
    fuerza solo la vista en planta (territorios sin perfil).
    """
    base = workspace / "plots" / "paneles"
    base.mkdir(parents=True, exist_ok=True)
    huella = hashlib.sha1(cache_key.encode("utf-8")).hexdigest()[:20]
    destino = base / f"{huella}.png"
    return _renderizar_core(
        workspace,
        destino,
        eventos,
        fuente,
        resumen,
        modo=modo,
    )
