"""Adaptador de Seisan: select.out → catálogo plano y arribos canónicos."""

from __future__ import annotations

import csv
import logging
import re
import statistics
from datetime import datetime, timedelta
from pathlib import Path

from .. import arribos_csv
from ..stations import ResolutorEstaciones
from .base import Adaptador as Base
from .base import PasoPlan

LOG = logging.getLogger(__name__)

RE_ID = re.compile(r"ID:(\d{14})")
RE_OPERADOR = re.compile(r"OP:(\S+)")

COLUMNAS_CALIDAD_SEISAN = (
    "standard_error",
    "azimuthal_gap",
    "used_phase_count",
    "associated_phase_count",
    "used_station_count",
    "associated_station_count",
    "minimum_distance_km",
    "maximum_distance_km",
    "median_distance_km",
    "horizontal_uncertainty",
    "depth_uncertainty",
    "error_ellipse",
    "origin_time_us",
    "evaluation_status",
    "software",
    "quality_source",
    "quality_derived",
    "quality_derived_fields",
    "unc_source",
    "unc_derived",
    "unc_derived_fields",
    "origin_source",
    "origin_derived",
    "origin_derived_fields",
    "magnitude_source",
    "magnitude_derived",
    "magnitude_derived_fields",
)


def _operador(linea: str) -> str:
    coincidencia = RE_OPERADOR.search(linea)
    if not coincidencia:
        return ""
    valor = coincidencia.group(1).strip()
    return "" if valor.upper() in {"TASK", "NONE", "NULL"} else valor


def _instante_encabezado(linea: str) -> datetime | None:
    """Hora del encabezado del evento en select.out.

    El encabezado tiene dos formas conocidas: ``2025  326 0024 19.2`` (mes y
    día compactos) y ``2026 11 1  019 52.0`` (mes y día separados). La hora del
    ``ID`` no siempre coincide con la del encabezado, así que se prefiere esta.
    """
    tokens = linea.split()
    if len(tokens) < 5 or not tokens[0].isdigit() or len(tokens[0]) != 4:
        return None
    indice_segundos = None
    for indice in range(1, min(7, len(tokens))):
        if re.match(r"^\d+\.\d+", tokens[indice]):
            indice_segundos = indice
            break
    if indice_segundos is None or indice_segundos < 2:
        return None
    indice_hhmm = indice_segundos - 1
    while indice_hhmm >= 1 and not tokens[indice_hhmm].isdigit():
        indice_hhmm -= 1
    if indice_hhmm < 1:
        return None
    hhmm = tokens[indice_hhmm]
    if len(hhmm) not in (3, 4):
        return None
    fecha = tokens[1:indice_hhmm]
    if len(fecha) == 1 and fecha[0].isdigit():
        compacto = fecha[0]
        if len(compacto) == 3:
            mes, dia = int(compacto[0]), int(compacto[1:])
        elif len(compacto) == 4:
            mes, dia = int(compacto[:2]), int(compacto[2:])
        else:
            return None
    elif len(fecha) == 2 and all(valor.isdigit() for valor in fecha):
        mes, dia = int(fecha[0]), int(fecha[1])
    else:
        return None
    try:
        hora = int(hhmm[:-2])
        minuto = int(hhmm[-2:])
        coincidencia_segundos = re.match(
            r"^(\d+\.\d+)", tokens[indice_segundos]
        )
        if coincidencia_segundos is None:
            return None
        segundo = float(coincidencia_segundos.group(1))
        return datetime(int(tokens[0]), mes, dia, hora, minuto) + timedelta(
            seconds=segundo
        )
    except ValueError:
        return None


def _calidad_encabezado(linea: str) -> dict:
    """RMS del encabezado del evento (columnas 52:56 de select.out)."""
    rms = _numero(linea[52:56])
    return {"standard_error": rms} if rms is not None else {}


def _calidad_gap(linea: str) -> dict:
    """GAP y errores de la línea ``GAP=`` de select.out.

    La línea trae, en orden, el azimutal gap y los errores horizontal y
    vertical. Se guarda la línea completa en ``error_ellipse`` para no perder
    los valores de confianza que trae después.
    """
    valores = []
    for token in linea.split()[1:]:
        valor = _numero(token.rstrip("E"))
        if valor is not None:
            valores.append(valor)
    datos = {"error_ellipse": linea.strip()}
    if valores:
        datos["azimuthal_gap"] = valores[0]
    if len(valores) >= 2:
        datos["horizontal_uncertainty"] = valores[1]
    if len(valores) >= 3:
        datos["depth_uncertainty"] = valores[2]
    return datos


def _estado_action(linea: str) -> str:
    if "STATUS:" not in linea:
        return ""
    resto = linea.split("STATUS:", 1)[1]
    return resto.split("ID:", 1)[0].strip()


def _calidad_bloque(bloque: dict) -> dict:
    """Calidad del evento y conteos derivados de sus fases."""
    fases = bloque.get("fases") or []
    usadas = [fase for fase in fases if (fase.get("peso") or 0) < 4]
    estaciones_usadas = {fase["estacion"] for fase in usadas}
    estaciones = {fase["estacion"] for fase in fases}
    distancias = [
        fase["distancia"]
        for fase in fases
        if fase.get("distancia") is not None
    ]
    calidad = dict(bloque.get("calidad") or {})
    calidad.update(
        {
            "used_phase_count": len(usadas),
            "associated_phase_count": len(fases),
            "used_station_count": len(estaciones_usadas),
            "associated_station_count": len(estaciones),
            "minimum_distance_km": min(distancias) if distancias else None,
            "maximum_distance_km": max(distancias) if distancias else None,
            "median_distance_km": (
                statistics.median(distancias) if distancias else None
            ),
            "origin_time_us": int(bloque["instante"].microsecond),
            "software": "seisan",
            "quality_source": "seisan",
            "quality_derived": "False",
            "quality_derived_fields": (
                "used_phase_count,associated_phase_count,"
                "used_station_count,associated_station_count,"
                "minimum_distance_km,maximum_distance_km,"
                "median_distance_km"
            ),
            "unc_source": "seisan",
            "unc_derived": "False",
            "unc_derived_fields": "",
            "origin_source": "seisan",
            "origin_derived": "False",
            "origin_derived_fields": "",
            "magnitude_source": "seisan",
            "magnitude_derived": "False",
            "magnitude_derived_fields": "",
        }
    )
    return calidad


def _verificar(workspace) -> None:
    ruta = Path(workspace) / "datos" / "salida_collect.csv"
    if not ruta.is_file() or ruta.stat().st_size <= 1:
        raise RuntimeError("select.out no produjo eventos analizables.")


def _numero(valor) -> float | None:
    try:
        return float(str(valor).strip())
    except (TypeError, ValueError):
        return None


def _instante(texto: str) -> datetime | None:
    limpio = " ".join(str(texto or "").strip().split())
    for formato in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(limpio, formato)
        except ValueError:
            continue
    return None


def _fila_hora(fila: dict) -> datetime | None:
    return _instante(fila.get("Fecha_Hora"))


def _enriquecer_catalogo(
    ruta: Path, calidad_por_indice: dict | None = None
) -> None:
    """Agrega ``id_evento`` y la calidad del evento al CSV normalizado.

    El valor de ``id_evento`` es el índice de la fila, el mismo que usa el
    contrato para el ``event_id`` y para enlazar los arribos. Las columnas de
    calidad se agregan al final para no alterar las ocho históricas.
    """
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        lector = csv.reader(archivo)
        filas = list(lector)
    if not filas:
        return
    cabecera = filas[0]
    for columna in ("id_evento",) + COLUMNAS_CALIDAD_SEISAN:
        if columna not in cabecera:
            cabecera.append(columna)
    posiciones = {nombre: indice for indice, nombre in enumerate(cabecera)}
    for numero_fila in range(1, len(filas)):
        fila = list(filas[numero_fila])
        fila = fila + [""] * (len(cabecera) - len(fila))
        indice = fila[0].strip() if fila else ""
        datos = {"id_evento": indice}
        datos.update((calidad_por_indice or {}).get(indice, {}))
        for columna, valor in datos.items():
            posicion = posiciones.get(columna)
            if posicion is not None:
                fila[posicion] = "" if valor is None else str(valor)
        filas[numero_fila] = fila
    temporal = ruta.with_suffix(ruta.suffix + ".tmp")
    with temporal.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.writer(archivo)
        escritor.writerows(filas)
    temporal.replace(ruta)


def _leer_eventos_normalizados(ruta: Path) -> list[dict]:
    filas = []
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        for posicion, fila in enumerate(csv.DictReader(archivo)):
            indice = str(fila.get("id_evento") or fila.get("") or posicion).strip()
            instante = _fila_hora(fila)
            if not indice or instante is None:
                continue
            filas.append(
                {
                    "indice": indice,
                    "instante": instante,
                    "lat": _numero(fila.get("Latitud")),
                    "lon": _numero(fila.get("Longitud")),
                }
            )
    return filas


def _es_linea_fase(linea: str) -> bool:
    """Indica si la línea tiene la estructura de una fase de select.out."""
    return bool(
        linea[1:6].strip()
        and linea[9:15].strip()
        and linea[18:22].strip().isdigit()
        and linea[23:29].strip()
    )


def _fase_desde_linea(linea: str, instante_evento: datetime) -> dict | None:
    """Convierte una línea de fase de select.out en un arribo.

    La fase ocupa columnas fijas. Las líneas de amplitud (IAML, AML) no son
    llegadas y se descartan.
    """
    estacion = linea[1:6].strip()
    componente = linea[6:8].strip()
    fase_raw = linea[9:15].strip()
    hrmm = linea[18:22].strip()
    segundos = linea[23:29].strip()
    if not estacion or not fase_raw or not hrmm.isdigit() or not segundos:
        return None
    peso = 0
    if fase_raw[-1].isdigit():
        peso = int(fase_raw[-1])
        fase_raw = fase_raw[:-1].strip()
    polaridad = linea[16:17].strip().upper()
    if polaridad not in ("C", "D"):
        polaridad = ""
    fase = arribos_csv.normalizar_fase(fase_raw)
    if not fase:
        return None
    try:
        hora_minuto = int(hrmm)
        hora = hora_minuto // 100
        minuto = hora_minuto % 100
        segundo = float(segundos)
    except ValueError:
        return None
    if hora > 23 or minuto > 59 or segundo < 0 or segundo >= 60:
        return None

    llegada = instante_evento.replace(
        hour=hora, minute=minuto, second=0, microsecond=0
    ) + timedelta(seconds=segundo)
    if llegada < instante_evento - timedelta(minutes=10):
        llegada += timedelta(days=1)

    return {
        "estacion": estacion.upper(),
        "componente": componente.upper(),
        "fase": fase,
        "fase_original": fase_raw,
        "llegada": llegada,
        "peso": peso,
        "polaridad": polaridad,
        "residual": _numero(linea[63:68]),
        "distancia": _numero(linea[71:75]),
        "azimut": _numero(linea[75:80]),
    }


def _bloques_select_out(ruta: Path) -> list[dict]:
    """Lee los bloques de fases de ``select.out``.

    Cada bloque se asocia con el ``ID`` del evento y con el operador del
    ``ACTION``. La fecha y hora exactas salen del ``ID``, no del encabezado,
    porque el encabezado tiene un formato variable.
    """
    bloques: list[dict] = []
    actual: dict | None = None
    encabezado: datetime | None = None
    calidad_pendiente: dict = {}
    en_fases = False
    try:
        lineas = ruta.read_text(encoding="latin-1", errors="replace").splitlines()
    except OSError:
        return bloques

    for linea in lineas:
        if not en_fases and linea.startswith(" "):
            posible = _instante_encabezado(linea)
            if posible is not None:
                encabezado = posible
                calidad_pendiente = _calidad_encabezado(linea)
        if not en_fases and linea.strip().startswith("GAP="):
            calidad_pendiente.update(_calidad_gap(linea))
            continue
        coincidencia_id = RE_ID.search(linea)
        if coincidencia_id:
            instante = encabezado
            if instante is None:
                try:
                    instante = datetime.strptime(
                        coincidencia_id.group(1), "%Y%m%d%H%M%S"
                    )
                except ValueError:
                    instante = None
            if instante is not None:
                actual = {
                    "instante": instante,
                    "operador": _operador(linea),
                    "calidad": dict(calidad_pendiente),
                    "fases": [],
                }
                estado = _estado_action(linea)
                if estado:
                    actual["calidad"]["evaluation_status"] = estado
            encabezado = None
            calidad_pendiente = {}
            continue
        operador = _operador(linea)
        if operador and actual is not None:
            actual["operador"] = operador
            continue
        if linea.lstrip().startswith("STAT SP IPHASW"):
            en_fases = True
            continue
        if not en_fases:
            continue
        if not linea.strip():
            if actual is not None and actual["fases"]:
                bloques.append(actual)
            actual = None
            en_fases = False
            continue
        if actual is None:
            en_fases = False
            continue
        if not _es_linea_fase(linea):
            bloques.append(actual)
            actual = None
            en_fases = False
            continue
        fase = _fase_desde_linea(linea, actual["instante"])
        if fase is not None:
            actual["fases"].append(fase)
    if actual is not None and actual["fases"]:
        bloques.append(actual)
    return bloques


def _elegir_evento(bloque: dict, eventos: list[dict]) -> dict | None:
    instante = bloque["instante"]
    candidatos = [
        (abs((evento["instante"] - instante).total_seconds()), evento)
        for evento in eventos
        if abs((evento["instante"] - instante).total_seconds()) <= 2.0
    ]
    if not candidatos:
        return None
    return min(candidatos, key=lambda item: item[0])[1]


class Adaptador(Base):
    formato = "local_select"
    tipo = "select"
    prefijo = ""
    prefijo_repetidos = "seisan"
    capacidades = frozenset(
        {"eventos", "origenes", "magnitudes", "arribos", "excluidos"}
    )

    def pasos(self, job, eventquery: str) -> list[PasoPlan]:
        return [
            PasoPlan("normalizar_seisan", "Procesar select.out", "revisaselect.py"),
            PasoPlan(
                "armar_catalogo",
                "Armar catálogo local",
                "revisacollect.py",
                verificar=_verificar,
            ),
            PasoPlan(
                "preparar_arribos",
                "Preparar arribos de Seisan",
                None,
                post=lambda workspace: self._preparar_arribos(job, workspace),
            ),
        ]

    def catalogo(self, job, referencia: str) -> str:
        return "datos/salida_collect.csv"

    def _ruta_fases(self, job) -> str:
        return f"datos/seisan_{job.inicio14}_{job.fin14}_fases.csv"

    def extensiones(self, job, referencia: str, workspace=None) -> dict[str, str]:
        if workspace is None:
            return {}
        ruta = Path(workspace) / self._ruta_fases(job)
        if not ruta.is_file():
            return {}
        try:
            with ruta.open(encoding="utf-8") as archivo:
                if sum(1 for _ in archivo) <= 1:
                    return {}
        except OSError:
            return {}
        return {"arribos": self._ruta_fases(job)}

    def _preparar_arribos(self, job, workspace) -> None:
        raiz = Path(workspace)
        catalogo = raiz / "datos" / "salida_collect.csv"
        if not catalogo.is_file():
            return
        try:
            eventos = _leer_eventos_normalizados(catalogo)
            origen = next(
                (
                    ruta
                    for ruta in (raiz / "select.out", raiz / "inputs" / "seisan__select.out")
                    if ruta.is_file()
                ),
                None,
            )
            if origen is None or not eventos:
                _enriquecer_catalogo(catalogo)
                return
            bloques = _bloques_select_out(origen)
            calidad: dict[str, dict] = {}
            for bloque in bloques:
                evento = _elegir_evento(bloque, eventos)
                if evento is not None:
                    calidad[str(evento["indice"])] = _calidad_bloque(bloque)
            _enriquecer_catalogo(catalogo, calidad)
            if not bloques:
                LOG.info("Seisan: select.out no trae bloques de fases.")
                return
            fuente = self._definicion() if hasattr(self, "_definicion") else None
            configuracion = getattr(fuente, "stations", {}) if fuente else {}
            resolutor = ResolutorEstaciones(configuracion)
            filas: list[dict] = []
            sin_evento = 0
            for bloque in bloques:
                evento = _elegir_evento(bloque, eventos)
                if evento is None:
                    sin_evento += 1
                    continue
                for fase in bloque["fases"]:
                    estacion = resolutor.resolver(
                        self.source_id or "seisan",
                        fase["estacion"],
                        lat_evento=evento["lat"],
                        lon_evento=evento["lon"],
                        instante=fase["llegada"],
                        distancia=fase["distancia"],
                    )
                    llegada_utc, llegada_us = arribos_csv.formatear_pick(
                        fase["llegada"]
                    )
                    filas.append(
                        {
                            "id_evento": evento["indice"],
                            "id_origen": "",
                            "id_pick": (
                                f"{evento['indice']}:{fase['estacion']}:"
                                f"{fase['componente']}:{fase['fase']}:{llegada_utc}"
                            ),
                            "red": estacion.network if estacion else "",
                            "estacion": fase["estacion"],
                            "loc": "",
                            "cha": fase["componente"],
                            "fase": fase["fase"],
                            "llegada_utc": llegada_utc,
                            "llegada_us": llegada_us,
                            "residual_s": fase["residual"] if fase["residual"] is not None else "",
                            "azimut": fase["azimut"] if fase["azimut"] is not None else "",
                            "distancia": fase["distancia"] if fase["distancia"] is not None else "",
                            "usada": "True" if fase["peso"] < 4 else "False",
                            # El canónico usa 0–1 con más alto = mejor. El W de
                            # Seisan va de 0 (mejor) a 4 (no usada); se conserva
                            # el valor original en ``peso_w`` para trazabilidad.
                            "peso": max(0.0, 1.0 - fase["peso"] / 4),
                            "peso_w": fase["peso"],
                            "polaridad": fase["polaridad"],
                            "modo_pick": "manual",
                            "pick_autor": bloque["operador"],
                            "tiene_magnitud": "No",
                            "est_lat": estacion.latitude if estacion else "",
                            "est_lon": estacion.longitude if estacion else "",
                            "est_elev": (
                                estacion.elevation_m
                                if estacion and estacion.elevation_m is not None
                                else ""
                            ),
                            "est_lugar": estacion.place if estacion else "",
                            "est_pais": estacion.country if estacion else "",
                            "base_datos": self.source_id or "seisan",
                            "est_lista": estacion.source_file if estacion else "",
                            "est_vigencia": estacion.time_basis if estacion else "",
                            "software": self.source_id or "seisan",
                            "origen_local": "",
                        }
                    )
            if filas:
                arribos_csv.escribir(raiz / self._ruta_fases(job), filas)
            LOG.info(
                "Seisan: %s arribos, %s bloques sin evento emparejado.",
                len(filas),
                sin_evento,
            )
        except Exception:  # noqa: BLE001
            LOG.exception("No se pudieron preparar los arribos de Seisan.")

    def _definicion(self):
        from .. import manifest as fuentes_manifest

        return fuentes_manifest.por_id(self.source_id)

    def prefijo_salida(self, source_id: str) -> str:
        return ""

    def archivo_no_publicados(self, source_id: str) -> str:
        return "no_pub_desde_2_5_estricto.csv"

    def archivo_no_actualizados(self, source_id: str) -> str:
        return "no_act_estricto.txt"
