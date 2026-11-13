"""Resumen de eventos por perfil de subducción para los paneles web.

Toma los catálogos de entrada y los listados de revisión del trabajo, les
asigna el perfil más cercano con ``asigna_perfiles`` del core y agrupa los
eventos para una lectura rápida del contexto sismotectónico.

Los eventos que quedan sin perfil se reparten en los territorios Nacional,
Insular, Antártico y Otros. Para Nacional e Insular se usa la clasificación
geográfica precisa de ``ubicacion.py`` (territorio chileno continental, costero,
marítimo e insular); los eventos de otros países o de alta mar quedan en Otros.
Las cajas de ``plotear.py`` se conservan para el Antártico y como respaldo.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path

from flask import current_app

from ..domain.catalogs import manifest as fuentes_manifest
from . import colores, plots, ubicacion
from .analysts import evento_visible, usuario_restringido
from .results import cargar_indice

# Cajas de referencia. Insular se ajustó a las islas oceánicas chilenas
# (Pascua, Sala y Gómez, Desventuradas y Juan Fernández), sin la costa
# continental ni Chiloé/Tierra del Fuego. El Antártico conserva la caja del
# proyecto base y Nacional se usa como respaldo cuando no hay geometrías.
TERRITORIOS = {
    "Nacional": ((-77.0, -66.0), (-56.0, -17.5)),
    "Insular": ((-112.0, -78.0), (-35.0, -25.0)),
    "Antártico": ((-76.0, -57.0), (-71.0, -53.0)),
}

TERRITORIOS_ORDEN = ("Nacional", "Insular", "Antártico", "Otros")

TIPOS = {
    "no_publicado": "No publicado",
    "no_actualizado": "No actualizado",
    "repetido": "Repetido",
}

def etiqueta_fuente(codigo: str) -> str:
    return fuentes_manifest.etiqueta(codigo)


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


def _texto(valor):
    return "" if valor is None else str(valor).strip()


def _leer_csv(ruta: Path) -> list[dict]:
    if not ruta.is_file():
        return []
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return [fila for fila in csv.DictReader(archivo) if any(fila.values())]


def _evento(
    fila: dict,
    *,
    fuente: str,
    fecha: str,
    lat: str,
    lon: str,
    prof: str,
    mag: str,
    tipo: str,
    analista: str = "",
    tipo_observacion: str | None = None,
    origen: dict | None = None,
    revision: str = "",
    publicacion: str = "",
    informes: list[str] | None = None,
    excluido: bool = False,
    percibido: str = "",
) -> dict | None:
    latitud = _numero(fila.get(lat))
    longitud = _numero(fila.get(lon))
    if latitud is None or longitud is None:
        return None
    profundidad = _numero(fila.get(prof))
    return {
        "id": "",
        "fecha": _texto(fila.get(fecha)),
        "lat": latitud,
        "lon": longitud,
        "latitud": latitud,
        "longitud": longitud,
        "prof": profundidad,
        "mag": _texto(fila.get(mag)),
        "magnitud": _texto(fila.get(mag)),
        "tipo": _texto(fila.get(tipo)),
        "analista": _texto(fila.get(analista)),
        "fuente": fuente,
        "fuente_etiqueta": etiqueta_fuente(fuente),
        "es_referencia": fuentes_manifest.es_referencia(fuente),
        # Paleta base: amarillo local/no percibido y rojo Eventquery percibido.
        "percibido": percibido,
        "color": colores.color_relleno(
            fuente, {"percibido": percibido}
        ),
        "tipo_observacion": tipo_observacion,
        "revision": revision,
        "publicacion": publicacion,
        "informes": informes or [],
        "excluido": excluido,
        "origen": origen or {},
        "perfil": None,
        "along_km": None,
        "perp_km": None,
        "residuo_km": None,
        "motivo": None,
        "sospechoso": False,
        "territorio": None,
    }


def _catalogo_info(workspace: Path, catalogo: str) -> dict | None:
    indice = cargar_indice(workspace)
    return (indice.get("catalogos") or {}).get(catalogo)


def _eventos_catalogo(workspace: Path, catalogo: str) -> tuple[str, list[dict]]:
    info = _catalogo_info(workspace, catalogo)
    if not info or not info.get("archivo"):
        return etiqueta_fuente(catalogo), []
    ruta = workspace / info["archivo"]
    eventos = []
    for indice_fila, fila in enumerate(_leer_csv(ruta)):
        evento = _evento(
            fila,
            fuente=catalogo,
            fecha="Fecha_Hora",
            lat="Latitud",
            lon="Longitud",
            prof="Prof.",
            mag="Mag.",
            tipo="Tipo_mag.",
            analista=(
                "Analista probable"
                if catalogo == fuentes_manifest.referencia().id
                else "Analista"
            ),
            percibido=(
                fila.get("Percep.", "")
                if catalogo == fuentes_manifest.referencia().id
                else ""
            ),
            origen={"tabla": "catalogos", "opcion": catalogo, "fila": indice_fila},
        )
        if evento is not None:
            evento["id"] = f"{catalogo}-{indice_fila}"
            eventos.append(evento)
    etiqueta = etiqueta_fuente(catalogo)
    return f"Catálogo {etiqueta}", eventos


def _eventos_no_publicados(workspace: Path) -> list[dict]:
    eventos = []
    for definicion in fuentes_manifest.locales():
        fuente = definicion.id
        ruta = workspace / "resultados" / f"no_publicados_{fuente}.csv"
        for indice_fila, fila in enumerate(_leer_csv(ruta)):
            evento = _evento(
                fila,
                fuente=fuente,
                fecha="Fecha_Hora",
                lat="Latitud",
                lon="Longitud",
                prof="Prof.",
                mag="Mag.",
                tipo="Tipo_mag.",
                analista="Analista",
                tipo_observacion="no_publicado",
                origen={
                    "tabla": "no_publicados",
                    "opcion": fuente,
                    "fila": indice_fila,
                },
            )
            if evento is not None:
                evento["id"] = f"np-{fuente}-{indice_fila}"
                eventos.append(evento)
    return eventos


def _eventos_no_actualizados(workspace: Path) -> list[dict]:
    eventos = []
    for definicion in fuentes_manifest.locales():
        fuente = definicion.id
        ruta = workspace / "resultados" / f"no_actualizados_{fuente}.csv"
        for indice_fila, fila in enumerate(_leer_csv(ruta)):
            evento = _evento(
                fila,
                fuente=fuente,
                fecha="fecha_local",
                lat="lat_local",
                lon="lon_local",
                prof="prof_local",
                mag="mag_local",
                tipo="tipo_mag_local",
                analista="analista",
                tipo_observacion="no_actualizado",
                revision=_texto(fila.get("revision")),
                publicacion=_texto(fila.get("publicacion_probable")),
                origen={
                    "tabla": "no_actualizados",
                    "opcion": fuente,
                    "fila": indice_fila,
                },
            )
            if evento is not None:
                evento["id"] = f"na-{fuente}-{indice_fila}"
                eventos.append(evento)
    return eventos


def _fuente_para_informe(clave_informe: str) -> str:
    locales = sorted(
        fuentes_manifest.locales(), key=lambda fuente: len(fuente.id), reverse=True
    )
    for definicion in locales:
        prefijos = (definicion.id, definicion.format)
        if any(
            clave_informe == prefijo or clave_informe.startswith(prefijo + "_")
            for prefijo in prefijos
            if prefijo
        ):
            return definicion.id
    referencia = fuentes_manifest.referencia()
    if clave_informe == "publica" or clave_informe.startswith("publica_"):
        return referencia.id
    if clave_informe == referencia.id or clave_informe.startswith(referencia.id + "_"):
        return referencia.id
    return clave_informe.split("_", 1)[0]


def _eventos_repetidos(workspace: Path) -> list[dict]:
    """Todos los informes de repetidos, sin contar dos veces el mismo evento.

    Los informes ``amplio`` y ``estricto`` se solapan, y ``excluidos`` puede
    repetir eventos. La clave de deduplicación es fuente + fecha + coordenadas
    + profundidad; se conserva el conjunto de informes donde apareció.
    """
    vistos: dict[tuple, dict] = {}
    carpeta = workspace / "resultados"
    for ruta in sorted(carpeta.glob("repetidos_*.csv")):
        clave_informe = ruta.stem.replace("repetidos_", "")
        fuente = _fuente_para_informe(clave_informe)
        excluido = "exclu" in clave_informe
        for indice_fila, fila in enumerate(_leer_csv(ruta)):
            evento = _evento(
                fila,
                fuente=fuente,
                fecha="fecha_hora",
                lat="latitud",
                lon="longitud",
                prof="prof",
                mag="mag",
                tipo="tipomag",
                analista="analista",
                tipo_observacion="repetido",
                informes=[clave_informe],
                excluido=excluido,
                percibido=fila.get("percibido", ""),
                origen={
                    "tabla": "repetidos",
                    "opcion": clave_informe,
                    "fila": indice_fila,
                },
            )
            if evento is None:
                continue
            if fuente == fuentes_manifest.referencia().id and not evento["analista"]:
                partes = []
                for definicion in fuentes_manifest.locales():
                    for clave_analista in (
                        f"analista_{definicion.id}",
                        f"analista_{definicion.format}",
                    ):
                        valor = _texto(fila.get(clave_analista))
                        if valor:
                            partes.append(f"{definicion.label}: {valor}")
                            break
                evento["analista"] = "; ".join(partes)
            clave = (
                fuente,
                evento["fecha"],
                round(evento["lat"], 5),
                round(evento["lon"], 5),
                None if evento["prof"] is None else round(evento["prof"], 1),
            )
            previo = vistos.get(clave)
            if previo is None:
                evento["id"] = f"rep-{len(vistos)}-{indice_fila}"
                vistos[clave] = evento
            else:
                for informe in evento["informes"]:
                    if informe not in previo["informes"]:
                        previo["informes"].append(informe)
                previo["excluido"] = previo["excluido"] and evento["excluido"]
    return list(vistos.values())


def _en_caja(lon: float, lat: float, limites) -> bool:
    (lon_min, lon_max), (lat_min, lat_max) = limites
    return lon_min <= lon <= lon_max and lat_min <= lat <= lat_max


def _territorio_evento(lat: float, lon: float) -> str:
    """Territorio del evento sin perfil según la geografía real.

    Se apoya en ``ubicacion.clasificar`` para no mandar a Nacional eventos de
    otros países o de alta mar. Las cajas quedan como respaldo sin geometrías.

    Nacional e Insular incluyen solo territorio chileno (continental, costero,
    marítimo o insular). Los eventos de otros países y de alta mar van a Otros.
    El Antártico conserva la caja del reclamo del proyecto base.
    """
    try:
        clasificacion = ubicacion.clasificar(lat, lon)
    except Exception:
        clasificacion = None

    if clasificacion:
        if clasificacion.get("pais") == "Chile":
            if _en_caja(lon, lat, TERRITORIOS["Insular"]):
                return "Insular"
            return "Nacional"
        if _en_caja(lon, lat, TERRITORIOS["Antártico"]):
            return "Antártico"
        return "Otros"

    # Respaldo sin geometrías disponibles: mismas cajas del proyecto base.
    for nombre in ("Nacional", "Insular", "Antártico"):
        if _en_caja(lon, lat, TERRITORIOS[nombre]):
            return nombre
    return "Otros"


def territorio_evento(lat: float, lon: float) -> str:
    """Territorio público de un evento: Nacional, Insular, Antártico u Otros."""
    return _territorio_evento(lat, lon)


def categorizar_territorio(eventos: list[dict]) -> dict[str, list[dict]]:
    """Categoriza eventos por territorio y agrega ``territorio`` a cada uno."""
    return _categorizar_territorio(eventos)


def _categorizar_territorio(eventos: list[dict]) -> dict[str, list[dict]]:
    resultado = {nombre: [] for nombre in TERRITORIOS_ORDEN}
    for evento in eventos:
        nombre = _territorio_evento(evento["lat"], evento["lon"])
        evento["territorio"] = nombre
        resultado[nombre].append(evento)
    return resultado


def _asignar(eventos: list[dict]) -> list:
    perfiles = plots._perfiles()
    if not perfiles:
        return eventos, perfiles
    plots._preparar_core()
    import asigna_perfiles as ap  # type: ignore

    ap.asignar_eventos(eventos, perfiles=perfiles)
    for evento in eventos:
        evento["sospechoso"] = plots._es_sospechoso(evento)
    return eventos, perfiles


def _resumen_perfil(perfil_id: str, eventos: list[dict]) -> dict:
    alongs = [
        evento["along_km"]
        for evento in eventos
        if evento.get("along_km") is not None
    ]
    lats = [evento["lat"] for evento in eventos]
    lons = [evento["lon"] for evento in eventos]
    return {
        "id": perfil_id,
        "eventos": len(eventos),
        "lat": sum(lats) / len(lats) if lats else None,
        "lon": sum(lons) / len(lons) if lons else None,
        "no_publicados": sum(
            1 for e in eventos if e.get("tipo_observacion") == "no_publicado"
        ),
        "no_actualizados": sum(
            1 for e in eventos if e.get("tipo_observacion") == "no_actualizado"
        ),
        "repetidos": sum(
            1 for e in eventos if e.get("tipo_observacion") == "repetido"
        ),
        "sospechosos": sum(1 for e in eventos if e.get("sospechoso")),
        "altas": sum(1 for e in eventos if e.get("revision") == "Alta"),
        "along_min": min(alongs) if alongs else None,
        "along_max": max(alongs) if alongs else None,
    }


def _resumen_territorio(nombre: str, eventos: list[dict]) -> dict:
    lats = [evento["lat"] for evento in eventos]
    lons = [evento["lon"] for evento in eventos]
    return {
        "nombre": nombre,
        "eventos": len(eventos),
        "lat": sum(lats) / len(lats) if lats else None,
        "lon": sum(lons) / len(lons) if lons else None,
        "sospechosos": sum(1 for e in eventos if e.get("sospechoso")),
        "no_publicados": sum(
            1 for e in eventos if e.get("tipo_observacion") == "no_publicado"
        ),
        "no_actualizados": sum(
            1 for e in eventos if e.get("tipo_observacion") == "no_actualizado"
        ),
        "repetidos": sum(
            1 for e in eventos if e.get("tipo_observacion") == "repetido"
        ),
    }


def _resumir(eventos: list[dict]) -> dict:
    """Conteos y grupos a partir de una lista de eventos ya categorizados."""
    grupos: dict[str, list[dict]] = {}
    sin_perfil: list[dict] = []
    for evento in eventos:
        pid = evento.get("perfil")
        if pid:
            grupos.setdefault(pid, []).append(evento)
        else:
            sin_perfil.append(evento)

    por_territorio: dict[str, list[dict]] = {
        nombre: [] for nombre in TERRITORIOS_ORDEN
    }
    for evento in sin_perfil:
        nombre = evento.get("territorio")
        if nombre in por_territorio:
            por_territorio[nombre].append(evento)

    return {
        "total": len(eventos),
        "con_perfil": sum(len(grupo) for grupo in grupos.values()),
        "sin_perfil": len(sin_perfil),
        "sospechosos": sum(1 for e in eventos if e.get("sospechoso")),
        "perfiles": [
            _resumen_perfil(pid, grupos[pid]) for pid in sorted(grupos)
        ],
        "territorios": [
            _resumen_territorio(nombre, por_territorio[nombre])
            for nombre in TERRITORIOS_ORDEN
            if por_territorio[nombre]
        ],
    }


def _archivos_fuente(workspace: Path, dataset: str) -> list[Path]:
    if dataset.startswith("catalogo_"):
        catalogo = dataset.split("_", 1)[1]
        info = _catalogo_info(workspace, catalogo)
        if info and info.get("archivo"):
            return [workspace / info["archivo"]]
        return []
    if dataset == "observaciones":
        return sorted(
            (workspace / "resultados").glob("no_publicados_*.csv")
        ) + sorted(
            (workspace / "resultados").glob("no_actualizados_*.csv")
        ) + sorted(
            (workspace / "resultados").glob("repetidos_*.csv")
        )
    return []


def _fingerprint(workspace: Path, dataset: str) -> str:
    partes = ["v5", dataset]
    for ruta in _archivos_fuente(workspace, dataset):
        try:
            estado = ruta.stat()
            partes.append(f"{ruta.name}:{estado.st_size}:{estado.st_mtime_ns}")
        except OSError:
            partes.append(f"{ruta.name}:falta")
    catalogo = (
        Path(current_app.config["RCS_CORE_DATA"])
        / current_app.config["RCS_CATALOGO_SISMICIDAD"]
    )
    try:
        estado = catalogo.stat()
        partes.append(f"{catalogo.name}:{estado.st_size}:{estado.st_mtime_ns}")
    except OSError:
        partes.append("catalogo_sismicidad:falta")
    for perfil in plots._perfiles():
        partes.append(str(perfil.get("id")))
    return hashlib.sha1("|".join(partes).encode("utf-8")).hexdigest()


def _ruta_cache(workspace: Path, dataset: str) -> Path:
    carpeta = workspace / "paneles"
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta / f"{dataset}.json"


def cargar(workspace: Path, dataset: str) -> dict:
    """Resumen del dataset, desde caché o calculado una vez."""
    cache = _ruta_cache(workspace, dataset)
    huella = _fingerprint(workspace, dataset)
    if cache.is_file():
        try:
            datos = json.loads(cache.read_text(encoding="utf-8"))
            if datos.get("huella") == huella:
                return datos
        except (OSError, ValueError):
            pass

    if dataset.startswith("catalogo_"):
        catalogo = dataset.split("_", 1)[1]
        titulo, eventos = _eventos_catalogo(workspace, catalogo)
    elif dataset == "observaciones":
        titulo = "Resultados"
        eventos = (
            _eventos_no_publicados(workspace)
            + _eventos_no_actualizados(workspace)
            + _eventos_repetidos(workspace)
        )
    else:
        raise ValueError(f"Dataset de panel desconocido: {dataset}")

    eventos, perfiles = _asignar(eventos)
    perfiles_por_id = {perfil["id"]: perfil for perfil in perfiles if perfil.get("id")}

    for evento in eventos:
        if evento.get("perfil") not in perfiles_por_id:
            evento["perfil"] = None
    _categorizar_territorio(
        [evento for evento in eventos if not evento.get("perfil")]
    )
    resumen = _resumir(eventos)

    datos = {
        "huella": huella,
        "dataset": dataset,
        "titulo": titulo,
        **resumen,
        "eventos": [
            {
                "id": evento["id"],
                "lat": evento["lat"],
                "lon": evento["lon"],
                "prof": evento["prof"],
                "fecha": evento["fecha"],
                "mag": evento.get("mag", ""),
                "tipo": evento.get("tipo", ""),
                "analista": evento.get("analista", ""),
                "perfil": evento.get("perfil"),
                "along_km": evento.get("along_km"),
                "tipo_observacion": evento.get("tipo_observacion"),
                "sospechoso": bool(evento.get("sospechoso")),
                "fuente": evento.get("fuente"),
                "fuente_etiqueta": evento.get("fuente_etiqueta", ""),
                "es_referencia": bool(evento.get("es_referencia")),
                "percibido": evento.get("percibido", ""),
                "color": evento.get("color", ""),
                "revision": evento.get("revision"),
                "informes": evento.get("informes", []),
                "excluido": evento.get("excluido", False),
                "territorio": evento.get("territorio"),
                "origen": evento.get("origen", {}),
            }
            for evento in eventos
        ],
    }
    try:
        cache.write_text(
            json.dumps(datos, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass
    return datos


def filtrar(datos: dict, tipo: str | None = None, fuente: str | None = None) -> dict:
    """Copia filtrada del panel, con los resúmenes recalculados."""
    eventos = [
        evento
        for evento in datos.get("eventos", [])
        if (not tipo or evento.get("tipo_observacion") == tipo)
        and (not fuente or evento.get("fuente") == fuente)
    ]
    filtrado = dict(datos)
    filtrado.update(_resumir(eventos))
    filtrado["eventos"] = eventos
    filtrado["filtro_tipo"] = tipo
    filtrado["filtro_fuente"] = fuente
    return filtrado


def filtrar_por_analista(datos: dict, usuario) -> dict:
    """Copia del panel con solo los eventos visibles para el analista."""
    if not usuario_restringido(usuario):
        return datos
    eventos = [
        evento
        for evento in datos.get("eventos", [])
        if evento_visible(evento, usuario)
    ]
    filtrado = dict(datos)
    filtrado.update(_resumir(eventos))
    filtrado["eventos"] = eventos
    return filtrado


def grupo_eventos(datos: dict, tipo: str, ident: str) -> dict | None:
    """Eventos y resumen de un perfil o de un territorio sin perfil."""
    if tipo == "perfil":
        eventos = [
            evento
            for evento in datos.get("eventos", [])
            if evento.get("perfil") == ident
        ]
        if not eventos:
            return None
        return {
            "tipo": "perfil",
            "id": ident,
            "titulo": f"Perfil {ident}",
            "eventos": eventos,
            "resumen": _resumen_perfil(ident, eventos),
        }
    if tipo == "territorio":
        eventos = [
            evento
            for evento in datos.get("eventos", [])
            if not evento.get("perfil") and evento.get("territorio") == ident
        ]
        if not eventos:
            return None
        return {
            "tipo": "territorio",
            "id": ident,
            "titulo": f"Territorio {ident}",
            "eventos": eventos,
            "resumen": _resumen_territorio(ident, eventos),
        }
    return None


def resumen_grupo_png(
    detalle: dict,
    *,
    dataset: str,
    dataset_titulo: str,
    tipo_titulo: str,
    fuente_titulo: str,
    job_id: str,
) -> dict:
    """Encabezado del PNG de un grupo: fuente, filtros y conteos, sin eventos."""
    total = len(detalle["eventos"])
    resumen = detalle["resumen"]
    titulo = (
        f"{detalle['titulo']} · {total} "
        f"evento{'s' if total != 1 else ''}"
    )
    if dataset == "observaciones":
        subtitulo = [
            f"{dataset_titulo} · Fuente: {fuente_titulo} · Tipo: {tipo_titulo}",
            (
                f"No publicados: {resumen.get('no_publicados', 0)} | "
                f"No actualizados: {resumen.get('no_actualizados', 0)} | "
                f"Repetidos: {resumen.get('repetidos', 0)} | "
                f"Sospechosos: {resumen.get('sospechosos', 0)}"
            ),
        ]
    else:
        subtitulo = [f"{dataset_titulo} · Fuente: {fuente_titulo}"]
    return {
        "titulo": titulo,
        "subtitulo": subtitulo,
        "filas": [],
        "nota": None,
        "pie": f"RCS Web · trabajo {job_id}",
    }


def conteos(datos: dict) -> dict:
    """Totales por tipo y por fuente, para las pestañas del panel."""
    tipos = {clave: 0 for clave in TIPOS}
    fuentes_por_tipo = {clave: {} for clave in TIPOS}
    fuentes_todos: dict[str, int] = {}
    for evento in datos.get("eventos", []):
        fuente = evento.get("fuente")
        tipo = evento.get("tipo_observacion")
        if tipo in tipos:
            tipos[tipo] += 1
            if fuente:
                fuentes_por_tipo[tipo][fuente] = (
                    fuentes_por_tipo[tipo].get(fuente, 0) + 1
                )
        if fuente:
            fuentes_todos[fuente] = fuentes_todos.get(fuente, 0) + 1
    return {
        "tipos": tipos,
        "fuentes_por_tipo": fuentes_por_tipo,
        "fuentes_todos": fuentes_todos,
    }


def _serie(valores) -> list:
    if valores is None:
        return []
    limpios = []
    for valor in valores:
        try:
            numero = float(valor)
        except (TypeError, ValueError):
            limpios.append(None)
            continue
        limpios.append(numero if math.isfinite(numero) else None)
    return limpios


def perfiles_grafico(ids: list[str]) -> dict:
    """Series de topografía y slab para dibujar el perfil de cada grupo."""
    por_id = {
        perfil.get("id"): perfil
        for perfil in plots._perfiles()
        if perfil.get("id")
    }
    datos = {}
    for pid in ids:
        perfil = por_id.get(pid)
        if perfil is None:
            continue
        slab = perfil.get("slab") or {}
        datos[pid] = {
            "slab_p": _serie(slab.get("p")),
            "slab_depth": _serie(slab.get("depth")),
            "slab_lon": _serie(slab.get("lon")),
            "slab_lat": _serie(slab.get("lat")),
            "topo_p": _serie(perfil.get("topo_p")),
            "topo_alt": _serie(perfil.get("topo_alt")),
        }
    return datos


def perfil_historico(perfil_id: str) -> dict | None:
    """Datos mínimos de un perfil para proyectar la sismicidad histórica.

    ``history.perfil`` necesita el id y las series del slab; se arman desde el
    mismo catálogo de perfiles que usa el resto de los paneles.
    """
    for perfil in plots._perfiles():
        if perfil.get("id") != perfil_id:
            continue
        slab = perfil.get("slab") or {}
        return {
            "id": perfil_id,
            "slab_p": _serie(slab.get("p")),
            "slab_depth": _serie(slab.get("depth")),
            "slab_lon": _serie(slab.get("lon")),
            "slab_lat": _serie(slab.get("lat")),
            "topo_p": _serie(perfil.get("topo_p")),
            "topo_alt": _serie(perfil.get("topo_alt")),
        }
    return None


def datasets_disponibles(workspace: Path) -> list[dict]:
    """Datasets que tienen datos en el trabajo, para el selector."""
    indice = cargar_indice(workspace)
    resultados = workspace / "resultados"
    hay_observaciones = any(resultados.glob("no_publicados_*.csv")) or any(
        resultados.glob("no_actualizados_*.csv")
    ) or any(resultados.glob("repetidos_*.csv"))
    opciones = []
    if hay_observaciones:
        opciones.append(
            {
                "clave": "observaciones",
                "titulo": "Resultados",
                "grupo": "Resultados",
            }
        )
    for definicion in fuentes_manifest.fuentes():
        if definicion.id in (indice.get("catalogos") or {}):
            opciones.append(
                {
                    "clave": f"catalogo_{definicion.id}",
                    "titulo": f"Catálogo {definicion.label}",
                    "grupo": "Por catálogo",
                }
            )
    return opciones


__all__ = [
    "cargar",
    "conteos",
    "datasets_disponibles",
    "etiqueta_fuente",
    "filtrar",
    "grupo_eventos",
    "perfil_historico",
    "perfiles_grafico",
    "resumen_grupo_png",
    "TERRITORIOS",
    "TIPOS",
]
