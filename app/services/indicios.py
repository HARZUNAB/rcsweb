"""Indicios de anomalías en la identificación de fases.

Este módulo no clasifica la localización ni reemplaza ``sospechoso``. Trabaja
solo con los arribos canónicos y entrega evidencia de que las fases asociadas a
un evento no calzan: residuales altos, fases fuera de orden y picks
anteriores al origen. El estado publicado se usa únicamente como contexto para
distinguir una revisión prioritaria de un indicio de calidad de catálogo.

Los adaptadores son los responsables de entregar los arribos con su residual
resuelto. Si una fuente no lo trae y otra lo aporta, el enriquecimiento ocurre
en la capa de adaptadores y deja la procedencia en ``raw``. Aquí solo se lee el
resultado canónico.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from ..domain.catalogs import canonical
from ..domain.catalogs import manifest as fuentes_manifest
from . import formatting

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
UMBRAL_CONTEXTO_ESTACIONES = 5
UMBRAL_CONTEXTO_SIN_INVENTARIO = 8
UMBRAL_CONTEXTO_AZGAP = 180.0
MAX_PARES_DETALLE = 40
ESQUEMA_INDICIOS = 3

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
    "publicado",
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


def _publicados(workspace: Path, source_id: str) -> dict[str, list[tuple[float | None, float | None]]] | None:
    """Eventos locales que cruzaron con la referencia publicada.

    La comparación estricta deja ``datos/atribucion_<fuente>.csv``. Si el
    archivo no existe, el estado publicado queda desconocido: no se inventa.
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


def _publicado_evento(
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
    publicado: bool | None = None,
    sospechoso: bool | None = None,
    explicacion_sospechoso: str = "",
    perfil_disponible: bool | None = None,
) -> dict:
    """Evalúa un evento y devuelve sus indicios de fases y su evidencia."""
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
    con_residual = [
        arribo for arribo in usadas if _numero(arribo.get("residual")) is not None
    ]
    outliers = [
        arribo
        for arribo in fuertes
        if abs(_numero(arribo.get("residual")) or 0.0) > UMBRAL_RESIDUAL
    ]
    residuales = [abs(_numero(arribo.get("residual")) or 0.0) for arribo in fuertes]
    mediana = _mediana(residuales)
    extremo = any(
        abs(_numero(arribo.get("residual")) or 0.0) > UMBRAL_RESIDUAL_EXTREMO
        or (
            mediana is not None
            and mediana > 0
            and abs(_numero(arribo.get("residual")) or 0.0)
            > FACTOR_RESIDUAL_EXTREMO * mediana
        )
        for arribo in outliers
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
    anomalia = bool(anomalia_fuerte or fuera_de_orden_debiles)
    fuerza = "fuerte" if anomalia_fuerte else ("débil" if anomalia else "")
    if publicado is True:
        prioridad = "Alta" if anomalia_fuerte else "Media"
    elif publicado is False:
        prioridad = "Baja" if anomalia_fuerte else "Informativa"
    else:
        prioridad = "Sin evaluar"
    prioridad_orden = {
        "Alta": 5,
        "Media": 4,
        "Baja": 3,
        "Informativa": 2,
        "Sin evaluar": 1,
    }[prioridad]
    if anomalia_fuerte:
        patron = _patron(fuertes, outliers, fuera_de_orden, antes, extremo)
    elif fuera_de_orden_debiles:
        patron = "fuera_de_orden_debil"
    else:
        patron = _patron(fuertes, outliers, fuera_de_orden, antes, extremo)

    tipos: list[str] = []
    if outliers:
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
    for arribo in outliers:
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
            for arribo in fuertes
            if (_numero(arribo.get("residual")) or 0.0) > 0
        )
        negativos = sum(
            1
            for arribo in fuertes
            if (_numero(arribo.get("residual")) or 0.0) < 0
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
                "detalle": (
                    f"{positivos} residuales positivos y {negativos} negativos;"
                    " posible modelo, profundidad u origen"
                ),
            }
        )

    resumen = formatting.patron_texto(patron)
    if patron == "sistemático":
        resumen = (
            f"{formatting.patron_texto(patron)} | {len(outliers)} estaciones |"
            f" residual mediano {formatting.numero(mediana, 2, signo=True)} s"
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
                f"{formatting.patron_texto(patron)} | {len(outliers)} estaciones"
                f" | residual mediano"
                f" {formatting.numero(mediana, 2, signo=True)} s"
            )
        else:
            resumen = (
                f"{formatting.patron_texto(patron)}"
                f" | residual {principal['residual']} s"
                f" | peso {principal['peso']}"
            )

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
        "publicado": publicado,
        "revision_prioritaria": bool(publicado is True and anomalia_fuerte),
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
        "n_outliers": len(outliers),
        "n_fuera_de_orden": len(fuera_de_orden),
        "n_fuera_de_orden_debiles": len(fuera_de_orden_debiles),
        "n_picks_antes_origen": len(antes),
        "tipos_indicio": ", ".join(tipos),
        "resumen": resumen,
        "residual_temporal": residual_temporal,
        "residual_fuentes": ", ".join(fuentes_residual),
        "sospechoso": sospechoso,
        "explicacion_sospechoso": explicacion_sospechoso,
        "evidencia": evidencia,
        "evidencia_principal": _evidencia_principal(evidencia),
    }


def estado_publicado(workspace: Path, source_id: str, evento: dict) -> bool | None:
    """Estado publicado de un evento, según la atribución de la comparación."""
    return _publicado_evento(evento, _publicados(workspace, source_id))


def evaluar_desde_canonico(
    workspace: Path,
    source_id: str,
    evento: dict,
    *,
    publicado: bool | None = None,
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
        publicado=publicado,
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
    fila["publicado"] = _si_no(evento.get("publicado"))
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
        "publicados": 0,
        "residual_temporal": False,
    }

    for source_id in fuentes:
        eventos = canonical.leer_canonico(workspace, source_id)
        arribos = _agrupar_por_evento(canonical.leer_arribos(workspace, source_id))
        sin_arribos = _agrupar_por_evento(
            canonical.leer_estaciones_sin_arribos(workspace, source_id)
        )
        indice_publicados = _publicados(workspace, source_id)
        evaluados: list[dict] = []
        for evento in eventos:
            event_id = _texto(evento.get("event_id"))
            resultado = evaluar_evento(
                evento,
                arribos.get(event_id, []),
                sin_arribos.get(event_id, []),
                source_id=source_id,
                publicado=_publicado_evento(evento, indice_publicados),
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
            "publicados": sum(1 for evento in evaluados if evento["publicado"] is True),
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
        }
        resumen["fuentes"][source_id] = info
        for clave in total:
            if clave == "residual_temporal":
                total[clave] = total[clave] or info[clave]
            else:
                total[clave] += info[clave]

    resumen["total"] = total
    ruta_resumen(workspace).parent.mkdir(parents=True, exist_ok=True)
    ruta_resumen(workspace).write_text(
        json.dumps(resumen, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return resumen


def leer_resumen(workspace: Path) -> dict | None:
    ruta = ruta_resumen(workspace)
    if not ruta.is_file():
        return None
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


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
