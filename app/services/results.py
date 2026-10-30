"""Construcción y lectura de las tablas de resultados.

El worker toma los CSV/TXT que deja el pipeline y los normaliza en
``workspace/<job>/resultados/`` con nombres estables. La web solo lee esos
archivos: no depende de los formatos internos del core.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import sys
import unicodedata
from pathlib import Path

from flask import current_app

from . import borders
from .sources import FUENTES, etiqueta, nombre_atribucion, nombre_no_publicados

# Informes de repetidos comunes a todas las fuentes locales.
REP_PUBLICA = (
    ("publica_amplio", "rep_publica_amplio.txt", "Publicados · amplio"),
    ("publica_estricto", "rep_publica_estricto.txt", "Publicados · estricto"),
)


def rep_files(
    fuentes: list[str], labels: dict[str, str] | None = None
) -> tuple[tuple[str, str, str], ...]:
    """(clave, archivo, título) de los informes de repetidos por fuente."""
    labels = labels or {}
    opciones = list(REP_PUBLICA)
    for fuente in fuentes:
        nombre = labels.get(fuente, etiqueta(fuente))
        opciones.append(
            (
                f"{fuente}_amplio",
                f"rep_{fuente}_amplio.txt",
                f"{nombre} · amplio",
            )
        )
        opciones.append(
            (
                f"{fuente}_estricto",
                f"rep_{fuente}_estricto.txt",
                f"{nombre} · estricto",
            )
        )
        if fuente == "seisan":
            opciones.append(("seisan_exclu", "rep_seisan_exclu.txt", "Seisan · excluidos"))
    return tuple(opciones)


def rep_grupos(fuentes: list[str], labels: dict[str, str] | None = None) -> tuple[dict, ...]:
    """Agrupa los informes de repetidos para el menú de la interfaz."""
    labels = labels or {}
    grupos = [
        {
            "titulo": "Publicados",
            "opciones": [
                ("publica_amplio", "Amplio"),
                ("publica_estricto", "Estricto"),
            ],
        }
    ]
    for fuente in fuentes:
        opciones = [
            (f"{fuente}_amplio", "Amplio"),
            (f"{fuente}_estricto", "Estricto"),
        ]
        if fuente == "seisan":
            opciones.append(("seisan_exclu", "Excluidos"))
        grupos.append(
            {
                "titulo": labels.get(fuente, etiqueta(fuente)),
                "opciones": opciones,
            }
        )
    return tuple(grupos)


# Columnas visibles de «No actualizados», en el orden en que se muestran.
NO_ACT_COLUMNS = (
    ("fecha_local", "Fecha y hora (fuente)"),
    ("lat_local", "Latitud (fuente)"),
    ("lon_local", "Longitud (fuente)"),
    ("prof_local", "Prof. (km)"),
    ("mag_local", "Mag."),
    ("tipo_mag_local", "Tipo mag."),
    ("fecha_eventquery", "Fecha y hora (publicada)"),
    ("lat_eventquery", "Latitud publicada"),
    ("lon_eventquery", "Longitud publicada"),
    ("prof_eventquery", "Prof. publicada"),
    ("mag_eventquery", "Mag. publicada"),
    ("tipo_mag_eventquery", "Tipo mag. publicada"),
    ("analista", "Analista"),
    ("dt_seg", "Δt (s)"),
    ("dlat", "Δlat (°)"),
    ("dlon", "Δlon (°)"),
    ("dist_km", "Dist. (km)"),
    ("publicacion_probable", "Publicación probable"),
    ("revision", "Revisión"),
    ("revision_orden", "Orden de revisión"),
    ("discrepancias", "Parámetros que difieren"),
)

# Columnas que se usan para ordenar pero no se muestran.
COLUMNAS_OCULTAS = {"revision_orden", "_fila", "Frontera_km", "Frontera_pais"}

TABLAS = {
    "catalogos": {
        "titulo": "Catálogos",
        "descripcion": "Catálogos de entrada procesados en este trabajo.",
        "tipo": "catalogo",
        "opciones": [],
        "archivo": "",
    },
    "no_publicados": {
        "titulo": "No publicados",
        "descripcion": (
            "Eventos de la fuente local (magnitud ≥ 2.5) que no aparecen en el "
            "catálogo público de eventquery."
        ),
        "tipo": "fuentes",
        "opciones": [("seiscomp", "SeisComp"), ("seisan", "Seisan")],
        "archivo": "no_publicados_{clave}.csv",
    },
    "no_actualizados": {
        "titulo": "No actualizados",
        "descripcion": (
            "Eventos publicados cuyos parámetros difieren de la solución local "
            "a la precisión del flujo (coordenadas y 1 decimal)."
        ),
        "tipo": "fuentes",
        "opciones": [("seiscomp", "SeisComp"), ("seisan", "Seisan")],
        "archivo": "no_actualizados_{clave}.csv",
    },
    "repetidos": {
        "titulo": "Repetidos",
        "descripcion": "Posibles eventos duplicados detectados por fuente.",
        "tipo": "opciones",
        "opciones": [
            (clave, titulo) for clave, _archivo, titulo in rep_files(["seisan", "seiscomp"])
        ],
        "archivo": "repetidos_{clave}.csv",
    },
}

PER_PAGE = 50


# --------------------------------------------------------------------------- #
# Comparación numérica (espejo de comparacion.py del core)
# --------------------------------------------------------------------------- #
TOLERANCIA_COORDENADA = 0.005
RADIO_TIERRA_KM = 6371.0088


def _a_numero(texto):
    if texto is None:
        return None
    limpio = str(texto).strip()
    if not limpio:
        return None
    try:
        return float(limpio)
    except ValueError:
        return None


def _mismo_numero(a, b, decimales, ignorar_signo=False, tolerancia=0.0):
    a = "" if a is None else str(a).strip()
    b = "" if b is None else str(b).strip()
    if not a or not b:
        return a == b
    na, nb = _a_numero(a), _a_numero(b)
    if na is None or nb is None:
        return a == b
    if ignorar_signo:
        na, nb = abs(na), abs(nb)
    if tolerancia:
        return round(abs(na - nb), decimales) <= tolerancia
    return round(na, decimales) == round(nb, decimales)


def _parametros_discrepantes(fila):
    campos = []
    if not _mismo_numero(
        fila.get("lat_eventquery"),
        fila.get("lat_local"),
        3,
        tolerancia=TOLERANCIA_COORDENADA,
    ):
        campos.append("lat")
    if not _mismo_numero(
        fila.get("lon_eventquery"),
        fila.get("lon_local"),
        3,
        tolerancia=TOLERANCIA_COORDENADA,
    ):
        campos.append("lon")
    if not _mismo_numero(
        fila.get("prof_eventquery"),
        fila.get("prof_local"),
        1,
        ignorar_signo=True,
    ):
        campos.append("prof")
    if not _mismo_numero(fila.get("mag_eventquery"), fila.get("mag_local"), 1):
        campos.append("mag")
    return campos


def _distancia_km(lat1, lon1, lat2, lon2):
    valores = [_a_numero(lat1), _a_numero(lon1), _a_numero(lat2), _a_numero(lon2)]
    if any(valor is None for valor in valores):
        return None
    la1, lo1, la2, lo2 = valores
    phi1, phi2 = math.radians(la1), math.radians(la2)
    dphi = math.radians(la2 - la1)
    dlambda = math.radians(lo2 - lo1)
    h = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * RADIO_TIERRA_KM * math.asin(min(1.0, math.sqrt(h)))


def _clave_coord(valor):
    numero = _a_numero(valor)
    if numero is None:
        return str(valor) if valor is not None else ""
    return round(numero, 3)


def _no_actualizados_local(filas):
    mejores = {}
    for fila in filas:
        if not _parametros_discrepantes(fila):
            continue
        clave = (
            fila.get("fecha_local", ""),
            _clave_coord(fila.get("lat_local")),
            _clave_coord(fila.get("lon_local")),
        )
        actual = mejores.get(clave)
        dt = _a_numero(fila.get("dt_seg"))
        dt_actual = _a_numero(actual.get("dt_seg")) if actual else None
        if actual is None or (dt if dt is not None else math.inf) < (
            dt_actual if dt_actual is not None else math.inf
        ):
            mejores[clave] = fila
    resultado = list(mejores.values())
    for fila in resultado:
        if not str(fila.get("dist_km", "")).strip():
            distancia = _distancia_km(
                fila.get("lat_eventquery"),
                fila.get("lon_eventquery"),
                fila.get("lat_local"),
                fila.get("lon_local"),
            )
            fila["dist_km"] = "" if distancia is None else round(distancia, 3)
    return resultado


def _preparar_core() -> Path:
    """Agrega el core al sys.path para reutilizar sus módulos puros."""
    core = Path(current_app.config["RCS_CORE_PATH"])
    if core.is_dir() and str(core) not in sys.path:
        sys.path.insert(0, str(core))
    return core


def _no_actualizados(filas):
    """Usa la regla del core si está montado; si no, la copia local."""
    _preparar_core()
    try:
        from comparacion import no_actualizados  # type: ignore

        return no_actualizados(filas)
    except Exception:
        return _no_actualizados_local(filas)


def _clasificar_no_actualizados(
    workspace: Path, fuente: str, filas_crudas: list[dict], filtradas: list[dict]
) -> None:
    """Agrega publicación probable y prioridad de revisión (cruce_noact)."""
    _preparar_core()
    try:
        import cruce_noact  # type: ignore

        filas_otras, motivo = cruce_noact.cargar_otra(str(workspace), fuente)
        cruce_noact.anotar(filtradas, filas_crudas, filas_otras, fuente, motivo)
    except Exception:
        for fila in filtradas:
            fila.setdefault("publicacion_probable", "")
            fila.setdefault("revision", "")
            fila.setdefault("revision_orden", "")


def _agregar_analistas(workspace: Path, filas: list[dict]) -> list[str]:
    """Agrega analista_seisan / analista_seiscomp a los repetidos publicados."""
    from .attribution import analistas_para_evento, cargar_atribucion

    indices = {fuente: cargar_atribucion(workspace, fuente) for fuente in ("seisan", "seiscomp")}
    if not any(indices.values()):
        return []

    columnas = []
    for fuente, indice in indices.items():
        if not indice:
            continue
        columna = f"analista_{fuente}"
        columnas.append(columna)
        for fila in filas:
            encontrados = analistas_para_evento(
                indice,
                fila.get("fecha_hora", ""),
                fila.get("latitud"),
                fila.get("longitud"),
            )
            nombres = []
            for entrada in encontrados or ():
                nombres.extend(entrada.get("analistas") or [])
            fila[columna] = ", ".join(nombres)
    return columnas


# --------------------------------------------------------------------------- #
# CSV
# --------------------------------------------------------------------------- #
def _limpiar_columna(nombre: str) -> str:
    limpio = (nombre or "").strip().lstrip("\ufeff")
    if limpio in ("", "Unnamed: 0"):
        return ""
    return limpio


def leer_csv(ruta: Path) -> tuple[list[str], list[dict]]:
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        lector = csv.DictReader(archivo)
        columnas = [_limpiar_columna(c) for c in (lector.fieldnames or [])]
        filas = []
        for cruda in lector:
            fila = {}
            for clave, valor in cruda.items():
                limpia = _limpiar_columna(clave)
                if limpia:
                    fila[limpia] = valor if valor is not None else ""
            filas.append(fila)
    return [c for c in columnas if c], filas


def escribir_csv(ruta: Path, columnas: list[str], filas: list[dict]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=columnas, extrasaction="ignore", restval="")
        escritor.writeheader()
        escritor.writerows(filas)


def _leer_repetidos(ruta: Path) -> tuple[list[str], list[dict]]:
    with ruta.open(encoding="utf-8-sig", errors="replace") as archivo:
        lineas = [linea.rstrip("\n") for linea in archivo if linea.strip()]
    if not lineas:
        return [], []
    columnas = lineas[0].split("\t")
    filas = []
    for linea in lineas[1:]:
        partes = linea.split("\t")
        if len(partes) != len(columnas):
            continue
        filas.append(dict(zip(columnas, partes)))
    return columnas, filas


# --------------------------------------------------------------------------- #
# Construcción
# --------------------------------------------------------------------------- #
def _contar(ruta: Path) -> int:
    if not ruta.is_file():
        return 0
    _columnas, filas = leer_csv(ruta)
    return len(filas)


def _firma_eventquery(workspace: Path, ruta: Path) -> str:
    """Huella del catálogo Eventquery y de las atribuciones que lo enriquecen."""
    partes = []
    for origen in (
        ruta,
        workspace / "datos" / "atribucion_seiscomp.csv",
        workspace / "datos" / "atribucion_seisan.csv",
    ):
        try:
            estado = origen.stat()
            partes.append(f"{origen.name}:{estado.st_size}:{estado.st_mtime_ns}")
        except OSError:
            partes.append(f"{origen.name}:falta")
    return hashlib.sha1("|".join(partes).encode("utf-8")).hexdigest()


def construir_resultados(workspace: Path, fuentes: list[str] | None = None) -> dict:
    """Normaliza las salidas del pipeline en ``resultados/``.

    ``fuentes`` son los códigos de las fuentes locales seleccionadas. Si no se
    indica, se asume el comportamiento histórico (Seisan y SeisComp).
    """
    if fuentes is None:
        fuentes = ["seisan", "seiscomp"]
    fuentes = [fuente for fuente in fuentes if fuente in FUENTES and FUENTES[fuente].es_local]

    resultados = workspace / "resultados"
    resultados.mkdir(parents=True, exist_ok=True)
    for viejo in resultados.glob("*.csv"):
        viejo.unlink(missing_ok=True)

    indice = {
        "no_publicados": {},
        "no_actualizados": {},
        "repetidos": {},
        "catalogos": {},
    }

    for fuente in fuentes:
        origen = workspace / "datos" / nombre_no_publicados(fuente)
        if not origen.is_file():
            continue
        columnas, filas = leer_csv(origen)
        destino = resultados / f"no_publicados_{fuente}.csv"
        escribir_csv(destino, columnas, filas)
        indice["no_publicados"][fuente] = {
            "archivo": destino.name,
            "filas": len(filas),
            "columnas": columnas,
        }

    for fuente in fuentes:
        origen = workspace / "datos" / nombre_atribucion(fuente)
        if not origen.is_file():
            continue
        destino = resultados / f"no_actualizados_{fuente}.csv"
        _columnas, filas_crudas = leer_csv(origen)
        filtradas = _no_actualizados(filas_crudas)
        _clasificar_no_actualizados(workspace, fuente, filas_crudas, filtradas)
        for fila in filtradas:
            fila["discrepancias"] = ", ".join(_parametros_discrepantes(fila))
        columnas = [clave for clave, _titulo in NO_ACT_COLUMNS]
        escribir_csv(destino, columnas, filtradas)
        indice["no_actualizados"][fuente] = {
            "archivo": destino.name,
            "filas": len(filtradas),
            "columnas": columnas,
        }

    for clave, nombre, _titulo in rep_files(fuentes):
        origen = workspace / "informes" / nombre
        if not origen.is_file():
            continue
        columnas, filas = _leer_repetidos(origen)
        if not columnas:
            continue
        if clave.startswith("publica"):
            columnas = columnas + _agregar_analistas(workspace, filas)
        destino = resultados / f"repetidos_{clave}.csv"
        escribir_csv(destino, columnas, filas)
        indice["repetidos"][clave] = {
            "archivo": destino.name,
            "filas": len(filas),
            "columnas": columnas,
        }

    catalogos = {
        "seisan": workspace / "datos" / "salida_collect.csv",
        "seiscomp": workspace / "datos" / "seiscomp_parametros.csv",
    }
    for clave in fuentes:
        ruta = catalogos.get(clave)
        if ruta is not None and ruta.is_file():
            indice["catalogos"][clave] = {
                "archivo": str(ruta.relative_to(workspace)),
                "filas": _contar(ruta),
            }
    eventquery = sorted((workspace / "datos").glob("new_2_*.csv"))
    if eventquery:
        origen = eventquery[0]
        from .attribution import enriquecer_eventquery

        columnas, filas = leer_csv(origen)
        columnas, filas = enriquecer_eventquery(workspace, columnas, filas)
        destino = resultados / "catalogo_eventquery.csv"
        escribir_csv(destino, columnas, filas)
        indice["catalogos"]["eventquery"] = {
            "archivo": "resultados/catalogo_eventquery.csv",
            "origen": str(origen.relative_to(workspace)),
            "filas": len(filas),
            "firma": _firma_eventquery(workspace, origen),
        }

    (resultados / "indice.json").write_text(
        json.dumps(indice, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return indice


def _escribir_indice(workspace: Path, indice: dict) -> None:
    ruta = workspace / "resultados" / "indice.json"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name("indice.tmp.json")
    temporal.write_text(
        json.dumps(indice, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporal.replace(ruta)


def _asegurar_catalogo_eventquery(workspace: Path, indice: dict) -> dict:
    """Genera el catálogo Eventquery enriquecido para trabajos existentes."""
    info = (indice.get("catalogos") or {}).get("eventquery")
    if not info:
        return indice
    archivo_rel = info.get("archivo") or ""
    origen_rel = info.get("origen") or (
        archivo_rel if not archivo_rel.startswith("resultados/") else ""
    )
    if not origen_rel:
        return indice
    origen = workspace / origen_rel
    if not origen.is_file():
        return indice
    firma = _firma_eventquery(workspace, origen)
    destino = workspace / "resultados" / "catalogo_eventquery.csv"
    if (
        archivo_rel.startswith("resultados/")
        and destino.is_file()
        and info.get("firma") == firma
    ):
        return indice

    from .attribution import enriquecer_eventquery

    columnas, filas = leer_csv(origen)
    columnas, filas = enriquecer_eventquery(workspace, columnas, filas)
    temporal = destino.with_name("catalogo_eventquery.tmp.csv")
    escribir_csv(temporal, columnas, filas)
    temporal.replace(destino)
    info["archivo"] = "resultados/catalogo_eventquery.csv"
    info["origen"] = origen_rel
    info["filas"] = len(filas)
    info["firma"] = firma
    _escribir_indice(workspace, indice)
    return indice


def cargar_indice(workspace: Path) -> dict:
    ruta = workspace / "resultados" / "indice.json"
    if not ruta.is_file():
        return {
            "no_publicados": {},
            "no_actualizados": {},
            "repetidos": {},
            "catalogos": {},
        }
    try:
        indice = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {
            "no_publicados": {},
            "no_actualizados": {},
            "repetidos": {},
            "catalogos": {},
        }
    return _asegurar_catalogo_eventquery(workspace, indice)


# --------------------------------------------------------------------------- #
# Lectura paginada
# --------------------------------------------------------------------------- #
def _normalizar(texto: str) -> str:
    sin_acentos = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in sin_acentos if not unicodedata.combining(c)).lower()


def _es_numerica(valores) -> bool:
    alguno = False
    for valor in valores:
        texto = str(valor).strip()
        if not texto:
            continue
        try:
            float(texto)
        except ValueError:
            return False
        alguno = True
    return alguno


RE_OPERADOR = re.compile(r"^(>=|<=|>|<|=)\s*(.+)$")
RE_RANGO = re.compile(r"^\s*(-?\d+(?:[.,]\d+)?)\s*\.\.\s*(-?\d+(?:[.,]\d+)?)\s*$")


def _a_numero_filtro(texto: str):
    return _a_numero(str(texto).replace(",", "."))


def _pasa_filtro(valor, patron: str, numerica: bool) -> bool:
    """Aplica un filtro de columna con sintaxis de texto o numérica."""
    patron = (patron or "").strip()
    if not patron:
        return True
    texto = "" if valor is None else str(valor).strip()

    if numerica:
        rango = RE_RANGO.match(patron)
        if rango:
            numero = _a_numero(texto)
            if numero is None:
                return False
            minimo = _a_numero_filtro(rango.group(1))
            maximo = _a_numero_filtro(rango.group(2))
            return minimo is not None and maximo is not None and minimo <= numero <= maximo

        operador = RE_OPERADOR.match(patron)
        if operador:
            numero = _a_numero(texto)
            objetivo = _a_numero_filtro(operador.group(2))
            if numero is None or objetivo is None:
                return False
            signo = operador.group(1)
            if signo == ">=":
                return numero >= objetivo
            if signo == ">":
                return numero > objetivo
            if signo == "<=":
                return numero <= objetivo
            if signo == "<":
                return numero < objetivo
            return abs(numero - objetivo) < 1e-9

        objetivo = _a_numero_filtro(patron)
        if objetivo is not None:
            numero = _a_numero(texto)
            return numero is not None and abs(numero - objetivo) < 1e-9

    return _normalizar(patron) in _normalizar(texto)


def _claves_frontera(columnas: list[str]):
    """Columnas de latitud/longitud según el tipo de tabla."""
    for lat, lon in (
        ("Latitud", "Longitud"),
        ("lat_local", "lon_local"),
        ("latitud", "longitud"),
    ):
        if lat in columnas and lon in columnas:
            return lat, lon
    return None


def claves_frontera(columnas: list[str]):
    return _claves_frontera(columnas)


def _insertar_frontera(columnas: list[str]) -> list[str]:
    if "Frontera" in columnas:
        return columnas
    posicion = len(columnas)
    for indice, columna in enumerate(columnas):
        if columna in ("Analista", "analista"):
            posicion = indice + 1
            break
    columnas.insert(posicion, "Frontera")
    return columnas


def _leer_filtrar_ordenar(
    workspace: Path,
    archivo: str,
    *,
    q: str = "",
    filtros: dict[str, str] | None = None,
    sort: str = "",
    direccion: str = "asc",
) -> tuple[list[str], list[dict], bool]:
    """Columnas visibles, filas filtradas/ordenadas y si el archivo existe."""
    raiz = workspace.resolve()
    ruta = (raiz / archivo).resolve() if "/" in archivo else (
        raiz / "resultados" / archivo
    ).resolve()
    if not ruta.is_file() or not ruta.is_relative_to(raiz):
        return [], [], False, {}, 0

    columnas, filas = leer_csv(ruta)
    total_archivo = len(filas)
    # La detección se hace antes de filtrar para que los campos numéricos no
    # pierdan su rango cuando una búsqueda deja pocas filas.
    numericas = {
        columna: _es_numerica(fila.get(columna, "") for fila in filas)
        for columna in columnas
    }
    for indice, fila in enumerate(filas):
        fila["_fila"] = indice
    claves = _claves_frontera(columnas)
    if claves:
        borders.anotar_filas(filas, *claves)
        _insertar_frontera(columnas)

    termino = _normalizar(q.strip())
    if termino:
        filas = [
            fila
            for fila in filas
            if termino in _normalizar(" ".join(str(v) for v in fila.values()))
        ]

    filtros = {
        columna: str(patron).strip()
        for columna, patron in (filtros or {}).items()
        if columna in columnas and str(patron).strip()
    }
    if filtros:
        filas = [
            fila
            for fila in filas
            if all(
                _pasa_filtro(
                    fila.get(columna, ""),
                    patron,
                    numericas.get(columna, False),
                )
                for columna, patron in filtros.items()
            )
        ]

    if sort == "Frontera":
        filas.sort(
            key=lambda f: (
                f.get("Frontera_km") is None,
                f.get("Frontera_km") or 0.0,
                _normalizar(str(f.get("Frontera", ""))),
            ),
            reverse=(direccion == "desc"),
        )
    elif sort == "revision":
        orden = {"Alta": 1, "Media": 2, "Baja": 3, "—": 4}
        filas.sort(
            key=lambda f: orden.get(str(f.get("revision", "")).strip(), 9),
            reverse=(direccion == "desc"),
        )
    elif sort in columnas:
        numerica = _es_numerica(fila.get(sort, "") for fila in filas)
        if numerica:
            filas.sort(
                key=lambda f: (
                    _a_numero(f.get(sort)) is None,
                    _a_numero(f.get(sort)) or 0.0,
                    _normalizar(str(f.get(sort, ""))),
                ),
                reverse=(direccion == "desc"),
            )
        else:
            filas.sort(
                key=lambda f: _normalizar(str(f.get(sort, ""))),
                reverse=(direccion == "desc"),
            )
    else:
        sort = ""

    visibles = [columna for columna in columnas if columna not in COLUMNAS_OCULTAS]
    return visibles, filas, True, numericas, total_archivo


def leer_tabla(
    workspace: Path,
    archivo: str,
    *,
    q: str = "",
    filtros: dict[str, str] | None = None,
    sort: str = "",
    direccion: str = "asc",
    page: int = 1,
    per_page: int = PER_PAGE,
) -> dict:
    columnas, filas, existe, numericas, total_archivo = _leer_filtrar_ordenar(
        workspace,
        archivo,
        q=q,
        filtros=filtros,
        sort=sort,
        direccion=direccion,
    )
    if not existe:
        return {
            "columnas": [],
            "filas": [],
            "total": 0,
            "total_archivo": 0,
            "page": 1,
            "pages": 1,
            "per_page": per_page,
            "sort": "",
            "direccion": "asc",
            "q": q,
            "filtros": {},
            "numericas": {},
            "existe": False,
        }

    total = len(filas)
    pages = max(1, math.ceil(total / per_page))
    page = max(1, min(page, pages))
    inicio = (page - 1) * per_page
    return {
        "columnas": columnas,
        "filas": filas[inicio : inicio + per_page],
        "total": total,
        "total_archivo": total_archivo,
        "page": page,
        "pages": pages,
        "per_page": per_page,
        "sort": sort,
        "direccion": direccion,
        "q": q,
        "filtros": {
            clave: valor
            for clave, valor in (filtros or {}).items()
            if clave in columnas and str(valor).strip()
        },
        "numericas": numericas,
        "existe": True,
    }


def exportar_filas(columnas: list[str], filas: list[dict]) -> bytes:
    """CSV con BOM para Excel a partir de columnas y filas ya resueltas."""
    buffer = io.StringIO()
    escritor = csv.DictWriter(
        buffer, fieldnames=columnas, extrasaction="ignore", restval=""
    )
    escritor.writeheader()
    escritor.writerows(filas)
    return buffer.getvalue().encode("utf-8-sig")


def exportar_csv(
    workspace: Path,
    archivo: str,
    *,
    q: str = "",
    filtros: dict[str, str] | None = None,
    sort: str = "",
    direccion: str = "asc",
) -> tuple[bytes, int]:
    """CSV filtrado completo (todas las páginas), con BOM para Excel."""
    columnas, filas, existe, _numericas, _total = _leer_filtrar_ordenar(
        workspace,
        archivo,
        q=q,
        filtros=filtros,
        sort=sort,
        direccion=direccion,
    )
    if not existe:
        return b"", 0
    return exportar_filas(columnas, filas), len(filas)


def exportar_seleccionados(
    workspace: Path,
    archivo: str,
    filas_ids: list[int],
) -> tuple[bytes, int]:
    """CSV de las filas marcadas, sin aplicar filtros.

    ``filas_ids`` son los ``_fila`` originales del archivo, de modo que la
    selección se mantiene al cambiar de página o de filtro.
    """
    columnas, filas, existe, _numericas, _total = _leer_filtrar_ordenar(
        workspace,
        archivo,
        q="",
        filtros={},
        sort="",
        direccion="asc",
    )
    if not existe:
        return b"", 0
    buscados = set(filas_ids)
    elegidas = [fila for fila in filas if fila.get("_fila") in buscados]
    return exportar_filas(columnas, elegidas), len(elegidas)
