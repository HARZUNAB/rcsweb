"""Construcción y lectura de las tablas de resultados.

El worker toma los CSV/TXT que deja el pipeline y los normaliza en
``workspace/<job>/resultados/`` con nombres estables. La web solo lee esos
archivos: no depende de los formatos internos del core.
"""

from __future__ import annotations

import csv
import json
import math
import sys
import unicodedata
from pathlib import Path

from flask import current_app

# (clave, título) de cada informe de repetidos que produce repetidos.py.
REP_FILES = (
    ("publica_amplio", "rep_publica_amplio.txt", "Publicados · amplio"),
    ("publica_estricto", "rep_publica_estricto.txt", "Publicados · estricto"),
    ("seisan_amplio", "rep_seisan_amplio.txt", "Seisan · amplio"),
    ("seisan_estricto", "rep_seisan_estricto.txt", "Seisan · estricto"),
    ("seisan_exclu", "rep_seisan_exclu.txt", "Seisan · excluidos"),
    ("seiscomp_amplio", "rep_seiscomp_amplio.txt", "SeisComp · amplio"),
    ("seiscomp_estricto", "rep_seiscomp_estricto.txt", "SeisComp · estricto"),
)

NO_PUBLICADOS = {
    "seiscomp": "no_pub_desde_2_5_seiscomp_estricto.csv",
    "seisan": "no_pub_desde_2_5_estricto.csv",
}

NO_ACTUALIZADOS = {
    "seiscomp": "atribucion_seiscomp.csv",
    "seisan": "atribucion_seisan.csv",
}

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
    ("discrepancias", "Parámetros que difieren"),
)

TABLAS = {
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
        "opciones": [(clave, titulo) for clave, _archivo, titulo in REP_FILES],
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


def _no_actualizados(filas):
    """Usa la regla del core si está montado; si no, la copia local."""
    core = Path(current_app.config["RCS_CORE_PATH"])
    if core.is_dir() and str(core) not in sys.path:
        sys.path.insert(0, str(core))
    try:
        from comparacion import no_actualizados  # type: ignore

        return no_actualizados(filas)
    except Exception:
        return _no_actualizados_local(filas)


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


def construir_resultados(workspace: Path) -> dict:
    """Normaliza las salidas del pipeline en ``resultados/``."""
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

    for fuente, nombre in NO_PUBLICADOS.items():
        origen = workspace / "datos" / nombre
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

    for fuente, nombre in NO_ACTUALIZADOS.items():
        origen = workspace / "datos" / nombre
        if not origen.is_file():
            continue
        destino = resultados / f"no_actualizados_{fuente}.csv"
        _columnas, filas = leer_csv(origen)
        filtradas = _no_actualizados(filas)
        for fila in filtradas:
            fila["discrepancias"] = ", ".join(_parametros_discrepantes(fila))
        columnas = [clave for clave, _titulo in NO_ACT_COLUMNS]
        escribir_csv(destino, columnas, filtradas)
        indice["no_actualizados"][fuente] = {
            "archivo": destino.name,
            "filas": len(filtradas),
            "columnas": columnas,
        }

    for clave, nombre, _titulo in REP_FILES:
        origen = workspace / "informes" / nombre
        if not origen.is_file():
            continue
        columnas, filas = _leer_repetidos(origen)
        if not columnas:
            continue
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
    for clave, ruta in catalogos.items():
        if ruta.is_file():
            indice["catalogos"][clave] = {
                "archivo": str(ruta.relative_to(workspace)),
                "filas": _contar(ruta),
            }
    eventquery = sorted((workspace / "datos").glob("new_2_*.csv"))
    if eventquery:
        indice["catalogos"]["eventquery"] = {
            "archivo": str(eventquery[0].relative_to(workspace)),
            "filas": _contar(eventquery[0]),
        }

    (resultados / "indice.json").write_text(
        json.dumps(indice, ensure_ascii=False, indent=2), encoding="utf-8"
    )
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
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {
            "no_publicados": {},
            "no_actualizados": {},
            "repetidos": {},
            "catalogos": {},
        }


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


def leer_tabla(
    workspace: Path,
    archivo: str,
    *,
    q: str = "",
    sort: str = "",
    direccion: str = "asc",
    page: int = 1,
    per_page: int = PER_PAGE,
) -> dict:
    raiz = workspace.resolve()
    ruta = (raiz / "resultados" / archivo).resolve()
    if not ruta.is_file() or not ruta.is_relative_to(raiz):
        return {
            "columnas": [],
            "filas": [],
            "total": 0,
            "page": 1,
            "pages": 1,
            "per_page": per_page,
            "sort": "",
            "direccion": "asc",
            "q": q,
            "existe": False,
        }

    columnas, filas = leer_csv(ruta)
    termino = _normalizar(q.strip())
    if termino:
        filas = [
            fila
            for fila in filas
            if termino in _normalizar(" ".join(str(v) for v in fila.values()))
        ]

    if sort in columnas:
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

    total = len(filas)
    pages = max(1, math.ceil(total / per_page))
    page = max(1, min(page, pages))
    inicio = (page - 1) * per_page
    return {
        "columnas": columnas,
        "filas": filas[inicio : inicio + per_page],
        "total": total,
        "page": page,
        "pages": pages,
        "per_page": per_page,
        "sort": sort,
        "direccion": direccion,
        "q": q,
        "existe": True,
    }
