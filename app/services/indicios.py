"""Indicios de anomalías en la identificación de fases.

Este módulo no clasifica la localización ni reemplaza ``sospechoso``. Trabaja
solo con los arribos canónicos y entrega evidencia de que las fases asociadas a
un evento no calzan: residuales altos, fases fuera de orden y picks
anteriores al origen. El cruce con Eventquery se usa únicamente como contexto para
distinguir una revisión prioritaria de un indicio de calidad de catálogo.

Los adaptadores son los responsables de entregar los arribos con su residual
resuelto. Si una fuente no lo trae y otra lo aporta, el enriquecimiento ocurre
en la capa de adaptadores y deja la procedencia en ``raw``. Aquí solo se lee el
resultado canónico.
"""

from __future__ import annotations

import csv
import json
import logging
import math
import statistics
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from ..domain.catalogs import canonical
from ..domain.catalogs import manifest as fuentes_manifest
from . import formatting, picks_coverage, wadati

UMBRAL_RESIDUAL = 5.0
UMBRAL_PESO = 0.5
UMBRAL_PESO_INFLUYENTE = 0.125
UMBRAL_RESIDUAL_FUERA_DE_ORDEN = 5.0
UMBRAL_TIEMPO_FUERA_DE_ORDEN_S = 2.0
UMBRAL_RESIDUAL_FUERA_DE_ORDEN_DEBIL = 5.0
SEPARACION_MINIMA_KM = 20.0
MIN_ESTACIONES_FASE = 3
UMBRAL_RESIDUAL_EXTREMO = 60.0
FACTOR_RESIDUAL_EXTREMO = 10.0
UMBRAL_SISTEMATICO_ESTACIONES = 5
UMBRAL_SISTEMATICO_PROPORCION = 0.7
UMBRAL_SISTEMATICO_MEDIANA = 2.0
UMBRAL_CONTEXTO_ESTACIONES = 5
UMBRAL_CONTEXTO_SIN_INVENTARIO = 8
UMBRAL_CONTEXTO_AZGAP = 180.0
MAX_PARES_DETALLE = 40
ESQUEMA_INDICIOS = 8

LOG = logging.getLogger(__name__)

ORDEN_PRIORIDAD = {
    "Alta": 5,
    "Media": 4,
    "Baja": 3,
    "Informativa": 2,
    "Sin evaluar": 1,
}


def prioridad_evento(con_cruce, fuerza, sospechoso) -> str:
    """Prioridad de revisión según cruce Eventquery, solución y fases.

    La duda de localización manda: un evento publicado y con solución
    sospechosa es Alta aunque las fases sean consistentes. La fase fuerte solo
    distingue la calidad de catálogo de un evento publicado con solución
    normal (Media) y el caso no publicado con solución sospechosa (Baja).
    """
    if con_cruce is None:
        return "Sin evaluar"
    confirmado = sospechoso is True
    fuerte = fuerza == "fuerte"
    if con_cruce:
        if confirmado:
            return "Alta"
        return "Media" if fuerte else "Informativa"
    if confirmado and fuerte:
        return "Baja"
    return "Informativa"


def _estado_cruce_texto(valor) -> str:
    if valor is True:
        return "con_cruce"
    if valor is False:
        return "sin_cruce"
    return "sin_evaluar"


CAMPOS_EVENTO = (
    "fuente",
    "evento",
    "id_evento_fuente",
    "fecha_hora",
    "latitud",
    "longitud",
    "profundidad_km",
    "magnitud",
    "analista",
    "region",
    "fila_catalogo",
    "cruce_eventquery",
    "revision_prioritaria",
    "anomalia",
    "fuerza",
    "prioridad",
    "prioridad_orden",
    "patron",
    "contexto",
    "extremo",
    "n_disponibles",
    "inventario_disponible",
    "n_usadas",
    "azimutal_gap",
    "max_residual_usado",
    "residual_mediana",
    "n_outliers",
    "n_fuera_de_orden",
    "n_fuera_de_orden_debiles",
    "n_picks_antes_origen",
    "tipos_indicio",
    "resumen",
    "residual_temporal",
    "residual_fuentes",
    "sospechoso",
    "explicacion_sospechoso",
    "wadati_n",
    "wadati_vp_vs",
    "wadati_r2",
    "wadati_dispersion",
    "wadati_calidad",
)

CAMPOS_DETALLE = (
    "fuente",
    "evento",
    "estacion",
    "red",
    "fase",
    "hora_pick",
    "t_seg",
    "residual",
    "peso",
    "peso_original",
    "distancia_km",
    "tipo_indicio",
    "detalle",
)


def ruta_indicios(workspace: Path) -> Path:
    return Path(workspace) / "resultados" / "indicios"


def ruta_eventos(workspace: Path, source_id: str) -> Path:
    return ruta_indicios(workspace) / f"indicios_{source_id}.csv"


def ruta_detalle(workspace: Path, source_id: str) -> Path:
    return ruta_indicios(workspace) / f"indicios_{source_id}_detalle.csv"


def ruta_resumen(workspace: Path) -> Path:
    return ruta_indicios(workspace) / "resumen.json"


def _texto(valor) -> str:
    return "" if valor is None else str(valor).strip()


def _numero(valor) -> float | None:
    try:
        return float(str(valor).strip())
    except (TypeError, ValueError):
        return None


def _instante(texto) -> datetime | None:
    limpio = " ".join(str(texto or "").strip().replace("Z", "").split())
    if not limpio:
        return None
    for formato in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ):
        try:
            return datetime.strptime(limpio, formato)
        except ValueError:
            continue
    return None


def _clave_tiempo(texto) -> str:
    instante = _instante(texto)
    if instante is None:
        return ""
    return instante.strftime("%Y-%m-%d %H:%M:%S")


def _clave_estacion(registro: dict) -> tuple[str, str]:
    red = _texto(registro.get("network") or registro.get("red"))
    estacion = _texto(registro.get("station") or registro.get("estacion"))
    return red, estacion


def _fase(registro: dict) -> str:
    fase = _texto(registro.get("phase") or registro.get("fase")).upper()
    if fase.startswith("P"):
        return "P"
    if fase.startswith("S"):
        return "S"
    return ""


def _influyente(arribo: dict) -> bool:
    """Una fase entra al análisis si su peso canónico supera 0,125.

    En la escala 0–4 que ve el analista eso equivale a peso 0–3. El peso 4
    significa que la fase no influyó en la solución y se excluye del análisis.
    Un peso ausente se considera influyente para no descartar picks por falta
    de dato.
    """
    peso = _numero(arribo.get("weight"))
    return peso is None or peso > UMBRAL_PESO_INFLUYENTE


def _mediana(valores: list[float]) -> float | None:
    return statistics.median(valores) if valores else None


def _azimutal_gap(azimuts: list[float]) -> float | None:
    if len(azimuts) < 2:
        return None
    normalizados = sorted(valor % 360.0 for valor in azimuts)
    huecos = [
        normalizados[i + 1] - normalizados[i]
        for i in range(len(normalizados) - 1)
    ]
    huecos.append(normalizados[0] + 360.0 - normalizados[-1])
    return max(huecos)


def _distancia_evento(evento: dict, arribo: dict) -> float | None:
    """Distancia epicentro-estación en km, calculada desde las coordenadas.

    El campo canónico ``distance_km`` no tiene la misma unidad en todas las
    fuentes: la exportación de SeisComp trae grados y la base Central trae km.
    Para comparar estaciones se recalcula con las coordenadas, que sí son
    homogéneas.
    """
    lat1 = _numero(evento.get("latitude"))
    lon1 = _numero(evento.get("longitude"))
    raw = arribo.get("raw") or {}
    lat2 = _numero(arribo.get("station_latitude"))
    if lat2 is None:
        lat2 = _numero(raw.get("est_lat"))
    lon2 = _numero(arribo.get("station_longitude"))
    if lon2 is None:
        lon2 = _numero(raw.get("est_lon"))
    if None in (lat1, lon1, lat2, lon2):
        return None
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    h = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(h)))


def _fuente_derivada(source_id: str) -> bool:
    """True si la fuente se llena desde otras fuentes locales (p. ej. Central)."""
    fuente = fuentes_manifest.por_id(source_id)
    return bool(fuente and fuente.derived)


def _referencias_cruzadas(workspace: Path) -> set[str]:
    """Filas de Eventquery con al menos un cruce local no derivado."""
    referencias: set[str] = set()
    for ruta in sorted((Path(workspace) / "datos").glob("atribucion_*.csv")):
        source_id = ruta.stem.removeprefix("atribucion_")
        if _fuente_derivada(source_id):
            continue
        try:
            with ruta.open(encoding="utf-8-sig", newline="") as archivo:
                for fila in csv.DictReader(archivo):
                    referencia = _texto(fila.get("n_fila_eventquery"))
                    if referencia:
                        referencias.add(referencia)
        except OSError:
            continue
    return referencias


def _indice_cruces_eventquery(workspace: Path, source_id: str) -> dict[str, list[tuple[float | None, float | None]]] | None:
    """Eventos locales que cruzaron con la referencia publicada.

    La comparación estricta deja ``datos/atribucion_<fuente>.csv``. Si el
    archivo no existe, el estado de cruce queda desconocido: no se inventa.
    """
    ruta = Path(workspace) / "datos" / f"atribucion_{source_id}.csv"
    if not ruta.is_file():
        return None
    indice: dict[str, list[tuple[float | None, float | None]]] = defaultdict(list)
    try:
        with ruta.open(encoding="utf-8-sig", newline="") as archivo:
            for fila in csv.DictReader(archivo):
                clave = _clave_tiempo(fila.get("fecha_local"))
                if not clave:
                    continue
                indice[clave].append(
                    (_numero(fila.get("lat_local")), _numero(fila.get("lon_local")))
                )
    except OSError:
        return None
    return dict(indice) or None


def _cruza_eventquery(
    evento: dict,
    indice: dict[str, list[tuple[float | None, float | None]]] | None,
) -> bool | None:
    if indice is None:
        return None
    clave = _clave_tiempo(evento.get("event_time"))
    if not clave or clave not in indice:
        return False
    lat = _numero(evento.get("latitude"))
    lon = _numero(evento.get("longitude"))
    for otra_lat, otra_lon in indice[clave]:
        if lat is None or lon is None or otra_lat is None or otra_lon is None:
            return True
        if abs(lat - otra_lat) <= 0.01 and abs(lon - otra_lon) <= 0.01:
            return True
    return False


def _contexto(
    usadas: list[dict],
    sin_arribos: list[dict],
    perfil_disponible: bool | None,
) -> dict:
    estaciones_usadas = {_clave_estacion(arribo) for arribo in usadas}
    n_usadas = len(estaciones_usadas)
    estaciones_inventario = {
        _clave_estacion(registro) for registro in sin_arribos
    }
    inventario_disponible = bool(estaciones_inventario)
    if inventario_disponible:
        n_disponibles = len(estaciones_usadas | estaciones_inventario)
    else:
        n_disponibles = n_usadas

    azimuts = [
        valor
        for valor in (
            _numero(arribo.get("azimuth"))
            for arribo in usadas
            if _fase(arribo) == "P"
        )
        if valor is not None
    ]
    azgap = _azimutal_gap(azimuts)
    if inventario_disponible:
        cobertura_suficiente = (
            n_disponibles >= UMBRAL_CONTEXTO_ESTACIONES
            and n_usadas >= UMBRAL_CONTEXTO_ESTACIONES
        )
    else:
        # Sin lista de estaciones sin arribo solo se conoce una cota inferior.
        cobertura_suficiente = n_usadas >= UMBRAL_CONTEXTO_SIN_INVENTARIO
    fuerte = (
        cobertura_suficiente
        and (azgap is None or azgap <= UMBRAL_CONTEXTO_AZGAP)
        and perfil_disponible is not False
    )
    return {
        "n_disponibles": n_disponibles,
        "n_usadas": n_usadas,
        "inventario_disponible": inventario_disponible,
        "azimutal_gap": round(azgap, 1) if azgap is not None else None,
        "contexto": "fuerte" if fuerte else "débil",
    }


def _patron(
    fuertes: list[dict],
    outliers: list[dict],
    fuera_de_orden: list[dict],
    antes: list[dict],
    extremo: bool,
) -> str:
    if extremo and outliers and len(outliers) <= 6 and len(fuertes) <= 8:
        return "puntual"
    if fuera_de_orden and outliers:
        return "mixto"
    if fuera_de_orden:
        return "fuera_de_orden"
    if antes:
        ids_antes = {id(arribo) for arribo in antes}
        otros = [arribo for arribo in outliers if id(arribo) not in ids_antes]
        if not otros:
            return "pick_antes_origen"
        return "mixto"
    if outliers:
        residuales = [
            _numero(arribo.get("residual")) for arribo in fuertes
        ]
        residuales = [valor for valor in residuales if valor is not None]
        positivos = sum(1 for valor in residuales if valor > 0)
        negativos = sum(1 for valor in residuales if valor < 0)
        total = max(1, positivos + negativos)
        if len(residuales) >= 5 and max(positivos, negativos) / total >= 0.7:
            return "sistemático"
        if len(outliers) <= 2 or len(outliers) / max(1, len(fuertes)) <= 0.3:
            return "puntual"
        return "mixto"
    if fuertes:
        return "sin_patron"
    return "sin_datos"


def _fuera_de_orden(
    fuertes: list[dict],
    evento: dict,
    fase: str,
) -> list[tuple[dict, dict, float]]:
    """Pares (cercana, lejana, diferencia de residual) fuera de orden.

    Se compara una sola fase por estación para no mezclar P con S. La
    distancia se recalcula desde las coordenadas porque el campo canónico no
    tiene la misma unidad en todas las fuentes. La separación mínima evita
    pares de estaciones casi coincidentes.
    """
    primeras: dict[tuple[str, str], dict] = {}
    for arribo in fuertes:
        if _fase(arribo) != fase or _numero(arribo.get("residual")) is None:
            continue
        if _distancia_evento(evento, arribo) is None:
            continue
        clave = _clave_estacion(arribo)
        if not clave[1]:
            continue
        actual = primeras.get(clave)
        instante = _instante(arribo.get("pick_time"))
        if actual is None:
            primeras[clave] = arribo
            continue
        previo = _instante(actual.get("pick_time"))
        if instante is not None and (previo is None or instante < previo):
            primeras[clave] = arribo

    ordenadas = sorted(
        primeras.values(),
        key=lambda arribo: _distancia_evento(evento, arribo) or 0.0,
    )
    if len(ordenadas) < MIN_ESTACIONES_FASE:
        return []

    pares: list[tuple[dict, dict, float]] = []
    for i, cercana in enumerate(ordenadas):
        distancia_cercana = _distancia_evento(evento, cercana)
        residual_cercana = _numero(cercana.get("residual"))
        for lejana in ordenadas[i + 1 :]:
            distancia_lejana = _distancia_evento(evento, lejana)
            residual_lejana = _numero(lejana.get("residual"))
            if None in (
                distancia_cercana,
                distancia_lejana,
                residual_cercana,
                residual_lejana,
            ):
                continue
            if distancia_lejana - distancia_cercana < SEPARACION_MINIMA_KM:
                continue
            diferencia = residual_cercana - residual_lejana
            if diferencia > UMBRAL_RESIDUAL_FUERA_DE_ORDEN:
                pares.append((cercana, lejana, diferencia))
    return pares


def _fuera_de_orden_debiles(
    influyentes: list[dict],
    evento: dict,
    fase: str,
) -> list[tuple[dict, dict, float, float]]:
    """Pares fuera de orden que no alcanzan la fuerza de la solución.

    Usa las fases P o S influyentes, es decir, con peso 0–3. Excluye las fases
    con peso 4 porque no aportaron a la solución. Exige que la estación más
    cercana llegue al menos 2 s después que una más lejana y que su residual
    sea alto; así se distingue de una simple diferencia de modelo. La prioridad
    sigue reservada a las anomalías fuertes.
    """
    primeras: dict[tuple[str, str], tuple[datetime, float, dict]] = {}
    for arribo in influyentes:
        if _fase(arribo) != fase:
            continue
        if _numero(arribo.get("residual")) is None:
            continue
        distancia = _distancia_evento(evento, arribo)
        instante = _instante(arribo.get("pick_time"))
        if distancia is None or instante is None:
            continue
        clave = _clave_estacion(arribo)
        if not clave[1]:
            continue
        actual = primeras.get(clave)
        if actual is None or instante < actual[0]:
            primeras[clave] = (instante, distancia, arribo)

    ordenadas = sorted(primeras.values(), key=lambda item: item[1])
    if len(ordenadas) < MIN_ESTACIONES_FASE:
        return []

    pares: list[tuple[dict, dict, float, float]] = []
    for i, (instante_cercana, distancia_cercana, cercana) in enumerate(ordenadas):
        residual_cercana = _numero(cercana.get("residual"))
        peso_cercana = _numero(cercana.get("weight")) or 0.0
        for instante_lejana, distancia_lejana, lejana in ordenadas[i + 1 :]:
            if distancia_lejana - distancia_cercana < SEPARACION_MINIMA_KM:
                continue
            if (
                instante_cercana - instante_lejana
            ).total_seconds() <= UMBRAL_TIEMPO_FUERA_DE_ORDEN_S:
                continue
            if abs(residual_cercana) <= UMBRAL_RESIDUAL_FUERA_DE_ORDEN_DEBIL:
                continue
            peso_lejana = _numero(lejana.get("weight")) or 0.0
            if peso_cercana >= UMBRAL_PESO and peso_lejana >= UMBRAL_PESO:
                continue
            diferencia = (instante_cercana - instante_lejana).total_seconds()
            pares.append((cercana, lejana, diferencia, residual_cercana))
    return pares


def _t_seg(arribo: dict, origen: datetime | None) -> float | None:
    instante = _instante(arribo.get("pick_time"))
    if instante is None or origen is None:
        return None
    return (instante - origen).total_seconds()


def _fila_detalle(
    source_id: str,
    evento: dict,
    arribo: dict,
    tipo: str,
    detalle: str,
    origen: datetime | None,
) -> dict:
    red, estacion = _clave_estacion(arribo)
    t_seg = _t_seg(arribo, origen)
    distancia = _distancia_evento(evento, arribo)
    return {
        "fuente": source_id,
        "evento": _texto(evento.get("event_id")),
        "estacion": estacion,
        "red": red,
        "fase": _texto(arribo.get("phase")),
        "hora_pick": _texto(arribo.get("pick_time")),
        "t_seg": formatting.numero(t_seg, 1),
        "residual": formatting.numero(arribo.get("residual"), 2, signo=True),
        "peso": formatting.peso_04_texto(arribo.get("weight")),
        "peso_original": formatting.peso_original(arribo.get("raw")),
        "distancia_km": formatting.numero(distancia, 1),
        "tipo_indicio": tipo,
        "detalle": detalle,
    }


def _evidencia_principal(evidencia: list[dict]) -> dict | None:
    """Fila de evidencia con mayor residual absoluto.

    Se usa en la cabecera del detalle para explicar qué arribo activó el
    indicio, sin obligar a abrir la tabla completa.
    """
    if not evidencia:
        return None

    def clave(item: dict) -> float:
        valor = _numero(item.get("residual"))
        return abs(valor) if valor is not None else -1.0

    return max(evidencia, key=clave)


def evaluar_evento(
    evento: dict,
    arribos: list[dict],
    sin_arribos: list[dict] | None = None,
    *,
    source_id: str = "",
    con_cruce: bool | None = None,
    sospechoso: bool | None = None,
    explicacion_sospechoso: str = "",
    perfil_disponible: bool | None = None,
) -> dict:
    """Evalúa un evento y devuelve sus señales de fases y su evidencia."""
    sin_arribos = sin_arribos or []
    origen = _instante(evento.get("event_time"))
    usadas = [
        arribo
        for arribo in arribos
        if arribo.get("is_used_in_solution") is True
    ]
    influyentes = [arribo for arribo in usadas if _influyente(arribo)]
    fuertes = [
        arribo
        for arribo in influyentes
        if _numero(arribo.get("residual")) is not None
        and (_numero(arribo.get("weight")) or 0.0) >= UMBRAL_PESO
    ]
    ids_fuertes = {id(arribo) for arribo in fuertes}
    con_residual = [
        arribo for arribo in usadas if _numero(arribo.get("residual")) is not None
    ]
    outliers = [
        arribo
        for arribo in fuertes
        if abs(_numero(arribo.get("residual")) or 0.0) > UMBRAL_RESIDUAL
    ]
    outliers_debiles = [
        arribo
        for arribo in influyentes
        if id(arribo) not in ids_fuertes
        and abs(_numero(arribo.get("residual")) or 0.0) > UMBRAL_RESIDUAL
    ]
    todos_outliers = outliers + outliers_debiles
    residuales = [
        abs(_numero(arribo.get("residual")) or 0.0) for arribo in influyentes
    ]
    mediana = _mediana(residuales)
    residuales_signados = [
        valor
        for valor in (
            _numero(arribo.get("residual")) for arribo in influyentes
        )
        if valor is not None
    ]
    residuales_influyentes = [abs(valor) for valor in residuales_signados]
    mediana_influyente = _mediana(residuales_influyentes)
    positivos_influyentes = sum(
        1 for valor in residuales_signados if valor > 0
    )
    negativos_influyentes = sum(
        1 for valor in residuales_signados if valor < 0
    )
    total_influyentes = max(
        1, positivos_influyentes + negativos_influyentes
    )
    proporcion_signo = (
        max(positivos_influyentes, negativos_influyentes) / total_influyentes
    )
    sistematico_moderado = (
        len(residuales_signados) >= UMBRAL_SISTEMATICO_ESTACIONES
        and proporcion_signo >= UMBRAL_SISTEMATICO_PROPORCION
        and mediana_influyente is not None
        and mediana_influyente >= UMBRAL_SISTEMATICO_MEDIANA
    )
    extremo = any(
        abs(_numero(arribo.get("residual")) or 0.0) > UMBRAL_RESIDUAL_EXTREMO
        or (
            mediana is not None
            and mediana > 0
            and abs(_numero(arribo.get("residual")) or 0.0)
            > FACTOR_RESIDUAL_EXTREMO * mediana
        )
        for arribo in todos_outliers
    )
    fuera_de_orden = []
    fuera_de_orden_debiles = []
    for fase in ("P", "S"):
        fuera_de_orden.extend(_fuera_de_orden(fuertes, evento, fase))
        fuera_de_orden_debiles.extend(
            _fuera_de_orden_debiles(influyentes, evento, fase)
        )
    antes = [
        arribo
        for arribo in fuertes
        if (_t_seg(arribo, origen) or 0.0) < 0
    ]
    contexto = _contexto(usadas, sin_arribos, perfil_disponible)
    anomalia_fuerte = bool(outliers or fuera_de_orden or antes)
    anomalia = bool(
        anomalia_fuerte or outliers_debiles or fuera_de_orden_debiles
    )
    fuerza = "fuerte" if anomalia_fuerte else ("débil" if anomalia else "")
    prioridad = prioridad_evento(con_cruce, fuerza, sospechoso)
    prioridad_orden = ORDEN_PRIORIDAD[prioridad]
    if anomalia_fuerte:
        patron = _patron(fuertes, outliers, fuera_de_orden, antes, extremo)
        base_patron = fuertes
    elif fuera_de_orden_debiles:
        patron = "fuera_de_orden_debil"
        base_patron = influyentes
    elif outliers_debiles:
        patron = _patron(
            influyentes, outliers_debiles, fuera_de_orden, antes, extremo
        )
        base_patron = influyentes
    else:
        patron = _patron(fuertes, outliers, fuera_de_orden, antes, extremo)
        base_patron = fuertes

    sistematico_no_concluyente = False
    if not anomalia and sistematico_moderado:
        patron = "sistemático"
        base_patron = influyentes
        sistematico_no_concluyente = True

    tipos: list[str] = []
    if todos_outliers:
        tipos.append("residual_alto")
    if fuera_de_orden:
        tipos.append("fuera_de_orden")
    if fuera_de_orden_debiles:
        tipos.append("fuera_de_orden_debil")
    if antes:
        tipos.append("pick_antes_origen")
    if patron == "sistemático":
        tipos.append("patron_sistematico")

    max_residual = max(
        (abs(_numero(arribo.get("residual")) or 0.0) for arribo in con_residual),
        default=None,
    )
    residuales_usadas = [
        _numero(arribo.get("residual"))
        for arribo in con_residual
        if _numero(arribo.get("residual")) is not None
    ]
    fuentes_residual = sorted(
        {
            _texto((arribo.get("raw") or {}).get("residual_fuente"))
            for arribo in usadas
            if (arribo.get("raw") or {}).get("residual_fuente")
        }
    )
    residual_temporal = any(
        bool((arribo.get("raw") or {}).get("residual_temporal"))
        or bool((arribo.get("raw") or {}).get("residual_fuente"))
        for arribo in usadas
    )

    evidencia: list[dict] = []
    for arribo in todos_outliers:
        detalle = (
            f"residual {formatting.numero(arribo.get('residual'), 2, signo=True)} s"
            f"; peso {formatting.peso_04_texto(arribo.get('weight'))}"
        )
        evidencia.append(
            _fila_detalle(source_id, evento, arribo, "residual_alto", detalle, origen)
        )
    for cercana, lejana, diferencia in fuera_de_orden[:MAX_PARES_DETALLE]:
        red_lejana, estacion_lejana = _clave_estacion(lejana)
        red_cercana, estacion_cercana = _clave_estacion(cercana)
        evidencia.append(
            _fila_detalle(
                source_id,
                evento,
                cercana,
                "fuera_de_orden",
                (
                    f"residual mayor que {red_lejana} {estacion_lejana}"
                    f" en {formatting.numero(diferencia, 2)} s"
                ),
                origen,
            )
        )
        evidencia.append(
            _fila_detalle(
                source_id,
                evento,
                lejana,
                "fuera_de_orden",
                (
                    f"residual menor que {red_cercana} {estacion_cercana}"
                    f" en {formatting.numero(diferencia, 2)} s"
                ),
                origen,
            )
        )
    for cercana, lejana, diferencia, residual in fuera_de_orden_debiles[
        :MAX_PARES_DETALLE
    ]:
        red_lejana, estacion_lejana = _clave_estacion(lejana)
        detalle = (
            f"llega {formatting.numero(diferencia, 2)} s después que"
            f" {red_lejana} {estacion_lejana}"
            f"; residual {formatting.numero(residual, 2, signo=True)} s"
            f"; peso {formatting.peso_04_texto(cercana.get('weight'))}"
        )
        evidencia.append(
            _fila_detalle(
                source_id,
                evento,
                cercana,
                "fuera_de_orden_debil",
                detalle,
                origen,
            )
        )
    for arribo in antes:
        t_seg = _t_seg(arribo, origen)
        detalle = (
            f"pick {formatting.numero(t_seg, 1)} s antes del origen"
        )
        evidencia.append(
            _fila_detalle(source_id, evento, arribo, "pick_antes_origen", detalle, origen)
        )
    if patron == "sistemático":
        positivos = sum(
            1
            for arribo in base_patron
            if (_numero(arribo.get("residual")) or 0.0) > 0
        )
        negativos = sum(
            1
            for arribo in base_patron
            if (_numero(arribo.get("residual")) or 0.0) < 0
        )
        detalle_sistematico = (
            f"{positivos} residuales positivos y {negativos} negativos;"
            " posible modelo, profundidad u origen"
        )
        if sistematico_no_concluyente:
            detalle_sistematico += (
                "; patrón no concluyente para la prioridad"
            )
        evidencia.append(
            {
                "fuente": source_id,
                "evento": _texto(evento.get("event_id")),
                "estacion": "",
                "red": "",
                "fase": "",
                "hora_pick": "",
                "t_seg": "",
                "residual": "",
                "peso": "",
                "distancia_km": "",
                "tipo_indicio": "patron_sistematico",
                "detalle": detalle_sistematico,
            }
        )

    resumen = formatting.patron_texto(patron)
    if patron == "sistemático":
        etiqueta = formatting.patron_texto(patron)
        if sistematico_no_concluyente:
            etiqueta = f"{etiqueta} (no concluyente)"
        resumen = (
            f"{etiqueta} | {len(base_patron)} estaciones |"
            f" residual mediano"
            f" {formatting.numero(mediana_influyente or mediana, 2, signo=True)} s"
        )
    elif evidencia:
        principal = evidencia[0]
        if principal["tipo_indicio"] == "pick_antes_origen":
            resumen = (
                f"{formatting.patron_texto(patron)} | t {principal['t_seg']} s"
                f" | peso {principal['peso']}"
            )
        elif principal["tipo_indicio"] == "patron_sistematico":
            resumen = (
                f"{formatting.patron_texto(patron)} | {len(base_patron)} estaciones"
                f" | residual mediano"
                f" {formatting.numero(mediana_influyente or mediana, 2, signo=True)} s"
            )
        else:
            resumen = (
                f"{formatting.patron_texto(patron)}"
                f" | residual {principal['residual']} s"
                f" | peso {principal['peso']}"
            )

    registro_wadati = []
    for arribo in arribos:
        red, estacion = _clave_estacion(arribo)
        registro_wadati.append(
            {
                "red": red,
                "estacion": estacion,
                "fase": _texto(arribo.get("phase")),
                "segundos": _t_seg(arribo, origen),
                "peso": _numero(arribo.get("weight")),
                "usada": (
                    "Sí"
                    if arribo.get("is_used_in_solution") is True
                    else "No"
                ),
            }
        )
    resultado_wadati = wadati.analizar(registro_wadati)

    return {
        "fuente": source_id,
        "evento": _texto(evento.get("event_id")),
        "id_evento_fuente": _texto(evento.get("source_event_id")),
        "fecha_hora": _texto(evento.get("event_time")),
        "latitud": evento.get("latitude", ""),
        "longitud": evento.get("longitude", ""),
        "profundidad_km": formatting.numero(evento.get("depth_km"), 1),
        "magnitud": formatting.numero(evento.get("magnitude"), 1),
        "analista": _texto(evento.get("analyst")),
        "region": _texto((evento.get("raw") or {}).get("region")),
        "fila_catalogo": evento.get("raw_index", ""),
        "cruce_eventquery": con_cruce,
        "revision_prioritaria": prioridad in ("Alta", "Media"),
        "anomalia": anomalia,
        "fuerza": fuerza,
        "prioridad": prioridad,
        "prioridad_orden": prioridad_orden,
        "patron": patron,
        "contexto": contexto["contexto"],
        "extremo": extremo,
        "n_disponibles": contexto["n_disponibles"],
        "inventario_disponible": contexto["inventario_disponible"],
        "n_usadas": contexto["n_usadas"],
        "azimutal_gap": formatting.numero(contexto["azimutal_gap"], 1),
        "max_residual_usado": formatting.numero(max_residual, 2),
        "residual_mediana": formatting.numero(
            _mediana(residuales_usadas), 2, signo=True
        ),
        "n_outliers": len(todos_outliers),
        "n_fuera_de_orden": len(fuera_de_orden),
        "n_fuera_de_orden_debiles": len(fuera_de_orden_debiles),
        "n_picks_antes_origen": len(antes),
        "tipos_indicio": ", ".join(tipos),
        "resumen": resumen,
        "residual_temporal": residual_temporal,
        "residual_fuentes": ", ".join(fuentes_residual),
        "sospechoso": sospechoso,
        "explicacion_sospechoso": explicacion_sospechoso,
        "wadati_n": resultado_wadati["n_pares"],
        "wadati_vp_vs": formatting.numero(
            resultado_wadati["vp_vs"], 2, cero_cercano=False
        ),
        "wadati_r2": formatting.numero(
            resultado_wadati["r2"], 2, cero_cercano=False
        ),
        "wadati_dispersion": formatting.numero(
            resultado_wadati["dispersion"], 2, cero_cercano=False
        ),
        "wadati_calidad": resultado_wadati["calidad"],
        "evidencia": evidencia,
        "evidencia_principal": _evidencia_principal(evidencia),
    }


def indice_cruces_eventquery(workspace: Path, source_id: str):
    """Índice de atribución reutilizable para resolver varios eventos."""
    return _indice_cruces_eventquery(workspace, source_id)


def estado_cruce_eventquery(
    workspace: Path,
    source_id: str,
    evento: dict,
    *,
    indice=None,
) -> bool | None:
    """Estado de cruce con Eventquery, según la atribución de la comparación."""
    if indice is None:
        indice = _indice_cruces_eventquery(workspace, source_id)
    return _cruza_eventquery(evento, indice)


def referencia_eventquery(
    workspace: Path,
    source_id: str,
    evento: dict,
) -> dict | None:
    """Fila de Eventquery que sostiene el cruce de un evento local.

    Devuelve la fecha de referencia y los datos del cruce. Se usa para abrir el
    catálogo publicado del día correcto, incluso si el evento local está cerca
    de la medianoche.
    """
    ruta = Path(workspace) / "datos" / f"atribucion_{source_id}.csv"
    if not ruta.is_file():
        return None
    clave = _clave_tiempo(evento.get("event_time"))
    lat = _numero(evento.get("latitude"))
    lon = _numero(evento.get("longitude"))
    if not clave:
        return None
    try:
        with ruta.open(encoding="utf-8-sig", newline="") as archivo:
            for fila in csv.DictReader(archivo):
                if _clave_tiempo(fila.get("fecha_local")) != clave:
                    continue
                otra_lat = _numero(fila.get("lat_local"))
                otra_lon = _numero(fila.get("lon_local"))
                if lat is None or lon is None:
                    return dict(fila)
                if (
                    otra_lat is not None
                    and otra_lon is not None
                    and abs(lat - otra_lat) <= 0.01
                    and abs(lon - otra_lon) <= 0.01
                ):
                    return dict(fila)
    except OSError:
        return None
    return None


def evaluar_desde_canonico(
    workspace: Path,
    source_id: str,
    evento: dict,
    *,
    con_cruce: bool | None = None,
    sospechoso: bool | None = None,
    explicacion_sospechoso: str = "",
    perfil_disponible: bool | None = None,
) -> dict:
    """Evalúa un evento canónico con sus arribos y estaciones sin arribo."""
    event_id = _texto(evento.get("event_id"))
    arribos = [
        arribo
        for arribo in canonical.leer_arribos(workspace, source_id)
        if _texto(arribo.get("event_id")) == event_id
    ]
    sin_arribos = [
        registro
        for registro in canonical.leer_estaciones_sin_arribos(workspace, source_id)
        if _texto(registro.get("event_id")) == event_id
    ]
    return evaluar_evento(
        evento,
        arribos,
        sin_arribos,
        source_id=source_id,
        con_cruce=con_cruce,
        sospechoso=sospechoso,
        explicacion_sospechoso=explicacion_sospechoso,
        perfil_disponible=perfil_disponible,
    )


def _agrupar_por_evento(registros: list[dict]) -> dict[str, list[dict]]:
    agrupados: dict[str, list[dict]] = defaultdict(list)
    for registro in registros:
        event_id = _texto(registro.get("event_id")) or _texto(
            registro.get("source_event_id")
        )
        if event_id:
            agrupados[event_id].append(registro)
    return agrupados


def _escribir_csv(ruta: Path, campos: tuple[str, ...], filas: list[dict]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=campos, extrasaction="ignore")
        escritor.writeheader()
        for fila in filas:
            escritor.writerow(fila)


def _si_no(valor) -> str:
    if valor is True:
        return "Sí"
    if valor is False:
        return "No"
    return "Desconocido"


def _registro_csv(evento: dict) -> dict:
    fila = dict(evento)
    fila.pop("evidencia", None)
    fila["cruce_eventquery"] = _estado_cruce_texto(
        evento.get("cruce_eventquery")
    )
    fila["revision_prioritaria"] = _si_no(evento.get("revision_prioritaria"))
    fila["anomalia"] = _si_no(evento.get("anomalia"))
    fila["extremo"] = _si_no(evento.get("extremo"))
    fila["inventario_disponible"] = _si_no(evento.get("inventario_disponible"))
    fila["residual_temporal"] = _si_no(evento.get("residual_temporal"))
    fila["sospechoso"] = _si_no(evento.get("sospechoso"))
    return fila


def generar_indicios(
    workspace: Path,
    fuentes: list[str] | tuple[str, ...] | None = None,
    *,
    job_id: str | None = None,
) -> dict:
    """Genera los reportes de indicios por fuente y el resumen del trabajo."""
    workspace = Path(workspace)
    if fuentes is None:
        fuentes = [fuente.id for fuente in fuentes_manifest.locales()]
    fuentes = [
        fuente
        for fuente in fuentes
        if "arribos" in fuentes_manifest.capacidades(fuente)
    ]
    resumen: dict = {
        "generado": datetime.now(UTC).isoformat(),
        "esquema": ESQUEMA_INDICIOS,
        "job_id": job_id or "",
        "fuentes": {},
    }
    total = {
        "eventos": 0,
        "evaluables": 0,
        "con_anomalia": 0,
        "con_anomalia_fuerte": 0,
        "con_anomalia_debil": 0,
        "revision_prioritaria": 0,
        "soluciones_con_cruce": 0,
        "residual_temporal": False,
        "picks_eventos": 0,
        "picks_sin_picar": 0,
        "picks_no_usadas": 0,
    }

    for source_id in fuentes:
        derivada = _fuente_derivada(source_id)
        eventos = canonical.leer_canonico(workspace, source_id)
        arribos = _agrupar_por_evento(canonical.leer_arribos(workspace, source_id))
        sin_arribos = _agrupar_por_evento(
            canonical.leer_estaciones_sin_arribos(workspace, source_id)
        )
        indice_cruces = (
            None if derivada else _indice_cruces_eventquery(workspace, source_id)
        )
        evaluados: list[dict] = []
        for evento in eventos:
            event_id = _texto(evento.get("event_id"))
            resultado = evaluar_evento(
                evento,
                arribos.get(event_id, []),
                sin_arribos.get(event_id, []),
                source_id=source_id,
                con_cruce=(
                    None
                    if derivada
                    else _cruza_eventquery(evento, indice_cruces)
                ),
            )
            evaluados.append(resultado)

        anomalos = [evento for evento in evaluados if evento["anomalia"]]
        detalle: list[dict] = []
        for evento in anomalos:
            detalle.extend(evento.pop("evidencia", []))
        for evento in evaluados:
            evento.pop("evidencia", None)
            evento.pop("evidencia_principal", None)

        _escribir_csv(
            ruta_eventos(workspace, source_id),
            CAMPOS_EVENTO,
            [_registro_csv(evento) for evento in anomalos],
        )
        _escribir_csv(ruta_detalle(workspace, source_id), CAMPOS_DETALLE, detalle)

        try:
            from . import picks_signal

            picks_signal.importar_reporte(workspace, source_id)
        except Exception:  # noqa: BLE001 - la señal es opcional
            LOG.exception("No se pudo importar la señal de cobertura de picks")
        try:
            picks = picks_coverage.generar(
                workspace,
                source_id,
                eventos=eventos,
                arribos=arribos,
                sin_arribos=sin_arribos,
            )
        except Exception:  # noqa: BLE001 - no invalida los indicios
            LOG.exception("No se pudo generar cobertura de picks")
            picks = {
                "eventos": 0,
                "sin_picar": 0,
                "no_usadas": 0,
                "fases_no_usadas": 0,
            }
        try:
            from . import picks_signal

            picks_signal.completar_reporte(workspace, source_id)
        except Exception:  # noqa: BLE001 - la señal es opcional
            LOG.exception("No se pudo completar la señal de cobertura de picks")

        info = {
            "eventos": len(evaluados),
            "evaluables": sum(1 for evento in evaluados if evento["n_usadas"] > 0),
            "con_anomalia": len(anomalos),
            "con_anomalia_fuerte": sum(
                1 for evento in evaluados if evento["fuerza"] == "fuerte"
            ),
            "con_anomalia_debil": sum(
                1 for evento in evaluados if evento["fuerza"] == "débil"
            ),
            "revision_prioritaria": sum(
                1 for evento in evaluados if evento["revision_prioritaria"]
            ),
            "soluciones_con_cruce": sum(
                1 for evento in evaluados if evento["cruce_eventquery"] is True
            ),
            "derived": derivada,
            "residual_temporal": any(
                evento["residual_temporal"] for evento in evaluados
            ),
            "residual_fuentes": sorted(
                {
                    fuente
                    for evento in evaluados
                    for fuente in _texto(evento.get("residual_fuentes")).split(", ")
                    if fuente
                }
            ),
            "inventario_disponible": any(
                evento["inventario_disponible"] for evento in evaluados
            ),
            "picks_eventos": picks["eventos"],
            "picks_sin_picar": picks["sin_picar"],
            "picks_no_usadas": picks["no_usadas"],
            "picks_fases_no_usadas": picks["fases_no_usadas"],
        }
        resumen["fuentes"][source_id] = info
        for clave in total:
            if clave == "residual_temporal":
                total[clave] = total[clave] or info[clave]
            else:
                total[clave] += info[clave]

    referencia = fuentes_manifest.referencia()
    total["eventos_referencia"] = len(
        canonical.leer_canonico(workspace, referencia.id)
    )
    referencias_cruzadas = _referencias_cruzadas(workspace)
    total["referencias_con_cruce"] = len(referencias_cruzadas)
    total["referencias_sin_cruce"] = max(
        0, total["eventos_referencia"] - len(referencias_cruzadas)
    )
    total["coincidencias_extra"] = max(
        0, total["soluciones_con_cruce"] - len(referencias_cruzadas)
    )
    total["referencia"] = referencia.id
    resumen["total"] = total
    ruta_resumen(workspace).parent.mkdir(parents=True, exist_ok=True)
    ruta_resumen(workspace).write_text(
        json.dumps(resumen, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    datos_cruce = detalle_cruce(workspace)
    if datos_cruce["huella"]:
        try:
            ruta_cruce_eventquery(workspace).write_text(
                json.dumps(datos_cruce, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass
    return resumen


def leer_resumen(workspace: Path) -> dict | None:
    ruta = ruta_resumen(workspace)
    if not ruta.is_file():
        return None
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def resumen_visible(
    workspace: Path,
    fuentes: list[str] | tuple[str, ...],
    usuario,
) -> dict:
    """Totales de revisión visibles para el usuario.

    Admin, supervisor y observador reciben el total del reporte. El analista
    recibe solo los eventos que le corresponden según ``evento_visible``.
    """
    from .analysts import evento_visible, usuario_restringido

    resumen = leer_resumen(workspace) or {}
    total = dict(resumen.get("total") or {})
    if not usuario_restringido(usuario):
        return total

    visible = {
        "con_anomalia": 0,
        "con_anomalia_fuerte": 0,
        "con_anomalia_debil": 0,
        "soluciones_con_cruce": 0,
        "eventos_referencia": total.get("eventos_referencia", 0),
        "referencias_con_cruce": total.get("referencias_con_cruce", 0),
        "referencias_sin_cruce": total.get("referencias_sin_cruce", 0),
        "coincidencias_extra": total.get("coincidencias_extra", 0),
        "residual_temporal": bool(total.get("residual_temporal")),
    }
    for fuente in fuentes:
        for fila in leer_indicios(workspace, fuente):
            if not evento_visible(fila, usuario):
                continue
            visible["con_anomalia"] += 1
            if fila.get("fuerza") == "fuerte":
                visible["con_anomalia_fuerte"] += 1
            elif fila.get("fuerza") == "débil":
                visible["con_anomalia_debil"] += 1
        if _fuente_derivada(fuente):
            continue
        indice = indice_cruces_eventquery(workspace, fuente)
        for evento in canonical.leer_canonico(workspace, fuente):
            if not evento_visible({"analista": evento.get("analyst")}, usuario):
                continue
            if _cruza_eventquery(evento, indice) is True:
                visible["soluciones_con_cruce"] += 1
    return visible


CRUCE_EVENTQUERY = "cruce_eventquery.json"
VERSION_CRUCE = 4
VENTANA_CANDIDATO_SEG = 120.0
VENTANA_CANDIDATO_KM = 50.0
VENTANA_COMPATIBLE_SEG = 6.0
VENTANA_COMPATIBLE_PROF_KM = 20.0
VENTANA_COMPATIBLE_MAG = 0.5
CRUCE_ESTRICTO_SEG = 3.0
CRUCE_ESTRICTO_GRADOS = 1.0
CRUCE_AMPLIO_SEG = 6.0
CRUCE_AMPLIO_GRADOS = 2.0
MOTIVO_SIN_CANDIDATO = (
    "Sin evento local dentro de 120 s y 50 km. "
    "El evento de referencia no tiene contraparte local comparable."
)


def ruta_cruce_eventquery(workspace: Path) -> Path:
    return ruta_indicios(workspace) / CRUCE_EVENTQUERY


def _huella_atribuciones(workspace: Path) -> dict[str, str]:
    """Tamaño y mtime de las atribuciones y del catálogo de referencia."""
    huella: dict[str, str] = {}
    carpetas = Path(workspace) / "datos"
    for ruta in sorted(carpetas.glob("atribucion_*.csv")):
        try:
            estado = ruta.stat()
        except OSError:
            continue
        huella[ruta.name] = f"{estado.st_size}-{int(estado.st_mtime)}"
    referencia = fuentes_manifest.referencia()
    fuentes = {referencia.id}
    for ruta in sorted(carpetas.glob("atribucion_*.csv")):
        fuentes.add(ruta.stem.removeprefix("atribucion_"))
    for source_id in sorted(fuentes):
        if _fuente_derivada(source_id):
            continue
        ruta_catalogo = canonical.ruta_canonica(workspace, source_id)
        if not ruta_catalogo.is_file():
            continue
        try:
            estado = ruta_catalogo.stat()
        except OSError:
            continue
        huella[f"catalogo/{source_id}/eventos.jsonl"] = (
            f"{estado.st_size}-{int(estado.st_mtime)}"
        )
    return huella


def _instante_evento(valor) -> datetime | None:
    texto = " ".join(str(valor or "").replace("T", " ").replace("Z", "").split())
    if not texto:
        return None
    try:
        return datetime.fromisoformat(texto)
    except ValueError:
        return None


def distancia_km(lat1, lon1, lat2, lon2) -> float | None:
    valores = [
        _numero(lat1),
        _numero(lon1),
        _numero(lat2),
        _numero(lon2),
    ]
    if any(valor is None for valor in valores):
        return None
    la1, lo1, la2, lo2 = valores
    phi1 = math.radians(la1)
    phi2 = math.radians(la2)
    dphi = math.radians(la2 - la1)
    dlambda = math.radians(lo2 - lo1)
    h = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(h)))


def _buscar_evento_local(
    eventos: list[dict], fecha: str, lat, lon
) -> dict | None:
    clave = _clave_tiempo(fecha)
    if not clave:
        return None
    candidatos = [
        evento
        for evento in eventos
        if _clave_tiempo(evento.get("event_time")) == clave
    ]
    if not candidatos:
        return None

    def distancia(evento: dict) -> float:
        otra_lat = _numero(evento.get("latitude"))
        otra_lon = _numero(evento.get("longitude"))
        if None in (otra_lat, otra_lon, lat, lon):
            return 0.0
        return abs(otra_lat - lat) + abs(otra_lon - lon)

    return min(candidatos, key=distancia)


def _grupos_extra(workspace: Path) -> list[dict]:
    """Referencias Eventquery con más de una solución local."""
    por_referencia: dict[str, dict] = {}
    carpetas = Path(workspace) / "datos"
    for ruta in sorted(carpetas.glob("atribucion_*.csv")):
        source_id = ruta.stem.removeprefix("atribucion_")
        if _fuente_derivada(source_id):
            continue
        try:
            with ruta.open(encoding="utf-8-sig", newline="") as archivo:
                for fila in csv.DictReader(archivo):
                    referencia = _texto(fila.get("n_fila_eventquery"))
                    if not referencia:
                        continue
                    fuente = _texto(fila.get("fuente")) or source_id
                    fecha_local = _texto(fila.get("fecha_local"))
                    lat = _numero(fila.get("lat_local"))
                    lon = _numero(fila.get("lon_local"))
                    grupo = por_referencia.setdefault(
                        referencia,
                        {
                            "fila": referencia,
                            "fecha_referencia": _texto(
                                fila.get("fecha_eventquery")
                            ),
                            "candidatos": {},
                        },
                    )
                    clave = (
                        fuente,
                        _clave_tiempo(fecha_local),
                        lat,
                        lon,
                    )
                    grupo["candidatos"][clave] = {
                        "fuente": fuente,
                        "fecha_local": fecha_local,
                        "lat": lat,
                        "lon": lon,
                        "analista": _texto(fila.get("analista")),
                        "dt_seg": _numero(fila.get("dt_seg")),
                        "dist_km": _numero(fila.get("dist_km")),
                    }
        except OSError:
            continue

    con_varias = [
        grupo
        for grupo in por_referencia.values()
        if len(grupo["candidatos"]) > 1
    ]
    if not con_varias:
        return []

    canonicos: dict[str, list[dict]] = {}
    for grupo in con_varias:
        for candidato in grupo["candidatos"].values():
            fuente = candidato["fuente"]
            if fuente not in canonicos:
                canonicos[fuente] = canonical.leer_canonico(workspace, fuente)
            candidato["evento"] = _buscar_evento_local(
                canonicos[fuente],
                candidato["fecha_local"],
                candidato["lat"],
                candidato["lon"],
            )

    salida = []
    for grupo in con_varias:
        soluciones = {}
        for candidato in grupo["candidatos"].values():
            evento = candidato.get("evento") or {}
            event_id = _texto(evento.get("event_id"))
            clave = (
                candidato["fuente"],
                event_id
                or (
                    candidato["fecha_local"],
                    candidato["lat"],
                    candidato["lon"],
                ),
            )
            soluciones[clave] = {
                "fuente": candidato["fuente"],
                "etiqueta": fuentes_manifest.etiqueta(candidato["fuente"]),
                "evento_local": event_id,
                "fila_local": evento.get("raw_index"),
                "fecha_local": candidato["fecha_local"],
                "analista": candidato["analista"],
                "dt_seg": candidato["dt_seg"],
                "dist_km": candidato["dist_km"],
            }
        lista = sorted(
            soluciones.values(),
            key=lambda item: (
                item["dist_km"] is None,
                item["dist_km"] if item["dist_km"] is not None else 1e9,
                item["fuente"],
                item["evento_local"],
            ),
        )
        if len(lista) < 2:
            continue
        salida.append(
            {
                "fila": grupo["fila"],
                "fecha_referencia": grupo["fecha_referencia"],
                "soluciones": lista,
                "extra": len(lista) - 1,
            }
        )
    salida.sort(
        key=lambda grupo: (
            grupo["fecha_referencia"],
            grupo["fila"],
        )
    )
    return salida


def _eventos_locales(workspace: Path) -> list[dict]:
    """Eventos canónicos de todas las fuentes locales no derivadas."""
    eventos = []
    for ruta in sorted((Path(workspace) / "datos").glob("atribucion_*.csv")):
        source_id = ruta.stem.removeprefix("atribucion_")
        if _fuente_derivada(source_id):
            continue
        for evento in canonical.leer_canonico(workspace, source_id):
            eventos.append((source_id, evento))
    return eventos


def _candidato_local(referencia: dict, locales: list[dict]) -> dict | None:
    instante = _instante_evento(referencia.get("event_time"))
    lat = _numero(referencia.get("latitude"))
    lon = _numero(referencia.get("longitude"))
    if instante is None:
        return None
    mejor = None
    for source_id, evento in locales:
        otro = _instante_evento(evento.get("event_time"))
        if otro is None:
            continue
        dt = abs((otro - instante).total_seconds())
        if dt > VENTANA_CANDIDATO_SEG:
            continue
        distancia = distancia_km(
            lat,
            lon,
            evento.get("latitude"),
            evento.get("longitude"),
        )
        if distancia is None or distancia > VENTANA_CANDIDATO_KM:
            continue
        puntaje = dt / VENTANA_CANDIDATO_SEG + distancia / VENTANA_CANDIDATO_KM
        if mejor is None or puntaje < mejor[0]:
            mejor = (
                puntaje,
                dt,
                distancia,
                source_id,
                evento,
            )
    if mejor is None:
        return None
    _, dt, distancia, source_id, evento = mejor
    raw = evento.get("raw") or {}
    motivos = []
    if dt > VENTANA_COMPATIBLE_SEG:
        motivos.append(f"Δt {dt:.1f} s")
    prof_ref = _numero(referencia.get("depth_km"))
    prof_local = _numero(evento.get("depth_km"))
    if prof_ref is None or prof_local is None:
        motivos.append("sin profundidad comparable")
    elif abs(prof_local - prof_ref) > VENTANA_COMPATIBLE_PROF_KM:
        motivos.append(f"Δprofundidad {abs(prof_local - prof_ref):.1f} km")
    mag_ref = _numero(referencia.get("magnitude"))
    mag_local = _numero(evento.get("magnitude"))
    if mag_ref is None or mag_local is None:
        motivos.append("sin magnitud comparable")
    elif abs(mag_local - mag_ref) > VENTANA_COMPATIBLE_MAG:
        motivos.append(f"Δmagnitud {abs(mag_local - mag_ref):.1f}")
    tipo_ref = _texto(referencia.get("magnitude_type"))
    tipo_local = _texto(evento.get("magnitude_type"))
    nota_tipo = ""
    if tipo_ref and tipo_local and tipo_ref != tipo_local:
        nota_tipo = f"tipo de magnitud distinto ({tipo_ref} / {tipo_local})"
    return {
        "fuente": source_id,
        "etiqueta": fuentes_manifest.etiqueta(source_id),
        "evento_local": _texto(evento.get("event_id")),
        "fila_local": evento.get("raw_index"),
        "fecha_local": _texto(evento.get("event_time")),
        "lat": evento.get("latitude"),
        "lon": evento.get("longitude"),
        "profundidad": evento.get("depth_km"),
        "magnitud": evento.get("magnitude"),
        "tipo_mag": tipo_local,
        "analista": _texto(evento.get("analyst")),
        "region": _texto(raw.get("Referencia")),
        "dt_seg": round(dt, 2),
        "dist_km": round(distancia, 2),
        "clasificacion": "compatible" if not motivos else "cercano",
        "motivo_clasificacion": " · ".join(motivos),
        "nota_magnitud": nota_tipo,
    }


def _criterio_cruce(dt: float, dlat, dlon) -> dict:
    """Explica si el par cae en el cruce estricto, amplio o en ninguno."""
    dlat = abs(dlat) if dlat is not None else None
    dlon = abs(dlon) if dlon is not None else None
    espacial_estricto = (
        dlat is not None
        and dlon is not None
        and dlat <= CRUCE_ESTRICTO_GRADOS
        and dlon <= CRUCE_ESTRICTO_GRADOS
    )
    espacial_amplio = (
        dlat is not None
        and dlon is not None
        and dlat <= CRUCE_AMPLIO_GRADOS
        and dlon <= CRUCE_AMPLIO_GRADOS
    )
    estricto = dt <= CRUCE_ESTRICTO_SEG and espacial_estricto
    amplio = dt <= CRUCE_AMPLIO_SEG and espacial_amplio
    if estricto:
        texto = ""
    elif amplio:
        fallos = []
        if dt > CRUCE_ESTRICTO_SEG:
            fallos.append(f"Δt {dt:.1f} s > {CRUCE_ESTRICTO_SEG:g} s")
        if not espacial_estricto:
            fallos.append(f"distancia > {CRUCE_ESTRICTO_GRADOS:g}°")
        detalle = " y ".join(fallos) or "parámetros fuera del estricto"
        texto = (
            f"Fuera del cruce estricto ({detalle}). "
            "Dentro del criterio amplio "
            f"(≤ {CRUCE_AMPLIO_SEG:g} s y ≤ {CRUCE_AMPLIO_GRADOS:g}°), "
            "visible en el informe de cobertura."
        )
    else:
        fallos = []
        if dt > CRUCE_AMPLIO_SEG:
            fallos.append(f"Δt {dt:.1f} s > {CRUCE_AMPLIO_SEG:g} s")
        if not espacial_amplio:
            fallos.append(f"distancia > {CRUCE_AMPLIO_GRADOS:g}°")
        detalle = " y ".join(fallos) or "Δt y distancia fuera de rango"
        texto = f"Fuera del criterio amplio ({detalle})."
    return {"estricto": estricto, "amplio": amplio, "texto": texto}


def _eventos_sin_cruce(workspace: Path) -> list[dict]:
    """Eventos de referencia sin ninguna solución local atribuida."""
    referencia = fuentes_manifest.referencia()
    eventos = canonical.leer_canonico(workspace, referencia.id)
    if not eventos:
        return []
    cruzadas = _referencias_cruzadas(workspace)
    faltantes = [
        evento
        for evento in eventos
        if _texto(evento.get("raw_index")) not in cruzadas
    ]
    if not faltantes:
        return []
    locales = _eventos_locales(workspace)
    salida = []
    for evento in faltantes:
        candidato = _candidato_local(evento, locales)
        raw = evento.get("raw") or {}
        diferencias = {}
        criterio = None
        if candidato is not None:
            for clave, propio, otro in (
                ("lat", evento.get("latitude"), candidato.get("lat")),
                ("lon", evento.get("longitude"), candidato.get("lon")),
                (
                    "profundidad",
                    evento.get("depth_km"),
                    candidato.get("profundidad"),
                ),
                (
                    "magnitud",
                    evento.get("magnitude"),
                    candidato.get("magnitud"),
                ),
            ):
                if propio is None or otro is None:
                    continue
                try:
                    diferencias[clave] = round(float(otro) - float(propio), 3)
                except (TypeError, ValueError):
                    continue
        if candidato is not None:
            criterio = _criterio_cruce(
                float(candidato["dt_seg"]),
                diferencias.get("lat"),
                diferencias.get("lon"),
            )
        salida.append(
            {
                "fila": evento.get("raw_index"),
                "evento": _texto(evento.get("event_id")),
                "fecha": _texto(evento.get("event_time")),
                "lat": evento.get("latitude"),
                "lon": evento.get("longitude"),
                "profundidad": evento.get("depth_km"),
                "magnitud": evento.get("magnitude"),
                "tipo_mag": _texto(evento.get("magnitude_type")),
                "region": _texto(raw.get("Referencia")),
                "percibido": _texto(raw.get("Percep.")),
                "candidato": candidato,
                "criterio": criterio,
                "diferencias": diferencias,
                "motivo": "" if candidato else MOTIVO_SIN_CANDIDATO,
            }
        )
    salida.sort(key=lambda item: (item["fecha"], item["fila"]))
    return salida


def detalle_cruce(workspace: Path) -> dict:
    """Detalle de coincidencias extra y eventos de referencia sin cruce."""
    extras = _grupos_extra(workspace)
    sin_cruce = _eventos_sin_cruce(workspace)
    return {
        "version": VERSION_CRUCE,
        "generado": datetime.now(UTC).isoformat(),
        "huella": _huella_atribuciones(workspace),
        "extras": {
            "total": sum(grupo["extra"] for grupo in extras),
            "grupos": extras,
        },
        "sin_cruce": {
            "total": len(sin_cruce),
            "eventos": sin_cruce,
        },
    }


def leer_detalle_cruce(workspace: Path) -> dict:
    """Lee el artefacto o lo calcula una vez si falta o cambió."""
    ruta = ruta_cruce_eventquery(workspace)
    huella = _huella_atribuciones(workspace)
    if ruta.is_file():
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            datos = None
        if (
            isinstance(datos, dict)
            and datos.get("version") == VERSION_CRUCE
            and datos.get("huella") == huella
        ):
            return datos
    datos = detalle_cruce(workspace)
    if not datos["huella"]:
        return datos
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(
            json.dumps(datos, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (ruta_indicios(workspace) / "coincidencias_extra.json").unlink(
            missing_ok=True
        )
    except OSError:
        pass
    return datos


def leer_indicios(workspace: Path, source_id: str) -> list[dict]:
    ruta = ruta_eventos(workspace, source_id)
    if not ruta.is_file():
        return []
    try:
        with ruta.open(encoding="utf-8-sig", newline="") as archivo:
            return list(csv.DictReader(archivo))
    except OSError:
        return []


def leer_detalle(workspace: Path, source_id: str, event_id: str) -> list[dict]:
    ruta = ruta_detalle(workspace, source_id)
    if not ruta.is_file():
        return []
    try:
        with ruta.open(encoding="utf-8-sig", newline="") as archivo:
            return [
                fila
                for fila in csv.DictReader(archivo)
                if _texto(fila.get("evento")) == _texto(event_id)
            ]
    except OSError:
        return []


def asegurar_indicios(
    workspace: Path,
    fuentes: list[str] | tuple[str, ...] | None = None,
    *,
    job_id: str | None = None,
) -> dict:
    """Genera el reporte si todavía no existe o si cambió el esquema."""
    resumen = leer_resumen(workspace)
    if resumen is None or resumen.get("esquema") != ESQUEMA_INDICIOS:
        return generar_indicios(workspace, fuentes, job_id=job_id)
    return resumen
