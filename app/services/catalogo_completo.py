"""Exporta el catálogo completo de una fuente local.

Genera un ZIP con:

- ``eventos.csv``: eventos canónicos con los bloques de calidad aplanados.
- ``arribos.csv``: todos los arribos de la fuente.
- ``estaciones_resumen.csv``: RMS, conteos, distancias y azimut por estación.
- ``LEEME.txt``: unidades, procedencia y versión del esquema.

El resumen por estación se calcula al exportar. Los bloques de calidad ya
vienen persistidos en el catálogo canónico.
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from app.domain.catalogs import canonical
from app.domain.catalogs.schema import SCHEMA_VERSION
from app.domain.catalogs.stations import distancia_km
from app.services.workspace import ruta_workspace


class CatalogoCompletoError(RuntimeError):
    """No se pudo generar el catálogo completo."""


# Fuentes con bloques de calidad completos en esta etapa.
FUENTES_HABILITADAS = frozenset({"seiscomp"})


CABECERA_EVENTOS = (
    "source_id",
    "event_id",
    "source_event_id",
    "origin_id",
    "database",
    "event_time",
    "latitude",
    "longitude",
    "depth_km",
    "magnitude",
    "magnitude_type",
    "agency",
    "analyst",
    "status",
    "revision",
    "is_preferred",
    "is_published",
    "raw_index",
    "quality_source",
    "quality_derived",
    "quality_used_phase_count",
    "quality_associated_phase_count",
    "quality_used_station_count",
    "quality_associated_station_count",
    "quality_depth_phase_count",
    "quality_standard_error",
    "quality_azimuthal_gap",
    "quality_secondary_azimuthal_gap",
    "quality_ground_truth_level",
    "quality_minimum_distance_km",
    "quality_maximum_distance_km",
    "quality_median_distance_km",
    "unc_source",
    "unc_derived",
    "unc_time_value",
    "unc_time_lower",
    "unc_time_upper",
    "unc_time_confidence",
    "unc_latitude_value",
    "unc_latitude_lower",
    "unc_latitude_upper",
    "unc_latitude_confidence",
    "unc_longitude_value",
    "unc_longitude_lower",
    "unc_longitude_upper",
    "unc_longitude_confidence",
    "unc_depth_value",
    "unc_depth_lower",
    "unc_depth_upper",
    "unc_depth_confidence",
    "unc_horizontal_value",
    "unc_horizontal_min",
    "unc_horizontal_max",
    "unc_horizontal_azimuth_max",
    "unc_ellipse_semimajor",
    "unc_ellipse_semiminor",
    "unc_ellipse_semiintermediate",
    "unc_ellipse_plunge",
    "unc_ellipse_azimuth",
    "unc_ellipse_rotation",
    "unc_preferred_description",
    "unc_confidence_level",
    "origin_source",
    "origin_derived",
    "origin_time_us",
    "origin_type",
    "origin_evaluation_mode",
    "origin_method_id",
    "origin_earth_model_id",
    "origin_depth_type",
    "magnitude_source",
    "magnitude_derived",
    "magnitude_uncertainty",
    "magnitude_lower_uncertainty",
    "magnitude_upper_uncertainty",
    "magnitude_confidence",
    "magnitude_station_count",
    "magnitude_azimuthal_gap",
    "magnitude_status",
    "magnitude_method_id",
)

CABECERA_ARRIBOS = (
    "source_id",
    "event_id",
    "source_event_id",
    "origin_id",
    "pick_id",
    "network",
    "station",
    "location",
    "channel",
    "phase",
    "pick_time",
    "pick_status",
    "is_used_in_solution",
    "weight",
    "polarity",
    "residual",
    "distance_km",
    "distance_km_calc",
    "azimuth",
    "snr",
    "qc",
    "picker_probability",
    "time_correction_s",
    "pick_author",
    "pick_agency",
    "pick_method",
    "station_magnitude",
    "station_magnitude_type",
    "has_station_magnitude",
    "station_magnitude_residual",
    "station_latitude",
    "station_longitude",
    "station_elevation_m",
    "station_place",
    "station_country",
    "database",
)

CABECERA_ESTACIONES = (
    "source_id",
    "network",
    "station",
    "location",
    "channel",
    "associated_phases",
    "used_phases",
    "residual_count",
    "residual_rms_s",
    "residual_mean_s",
    "residual_max_abs_s",
    "distance_min_km",
    "distance_max_km",
    "azimuth_mean_deg",
    "used_in_solution",
    "pick_authors",
    "derived",
)


def _iter_jsonl(ruta: Path):
    if not ruta.is_file():
        return
    with ruta.open(encoding="utf-8") as archivo:
        for linea in archivo:
            if linea.strip():
                try:
                    yield json.loads(linea)
                except ValueError:
                    continue


def _celda(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "True" if valor else "False"
    return str(valor)


def _numero(valor) -> float | None:
    try:
        return float(str(valor).strip())
    except (TypeError, ValueError):
        return None


def _aplanar_evento(evento: dict) -> dict:
    calidad = evento.get("origin_quality") or {}
    incertidumbre = evento.get("origin_uncertainty") or {}
    metadatos = evento.get("origin_metadata") or {}
    magnitud = evento.get("magnitude_metadata") or {}

    def bloque(prefijo: str, datos: dict) -> dict:
        return {
            f"{prefijo}_{clave}": valor
            for clave, valor in datos.items()
        }

    fila = {
        "source_id": evento.get("source_id"),
        "event_id": evento.get("event_id"),
        "source_event_id": evento.get("source_event_id"),
        "origin_id": evento.get("origin_id"),
        "database": evento.get("database"),
        "event_time": evento.get("event_time"),
        "latitude": evento.get("latitude"),
        "longitude": evento.get("longitude"),
        "depth_km": evento.get("depth_km"),
        "magnitude": evento.get("magnitude"),
        "magnitude_type": evento.get("magnitude_type"),
        "agency": evento.get("agency"),
        "analyst": evento.get("analyst"),
        "status": evento.get("status"),
        "revision": evento.get("revision"),
        "is_preferred": evento.get("is_preferred"),
        "is_published": evento.get("is_published"),
        "raw_index": evento.get("raw_index"),
        "quality_source": calidad.get("source"),
        "quality_derived": calidad.get("derived"),
        "quality_used_phase_count": calidad.get("used_phase_count"),
        "quality_associated_phase_count": calidad.get(
            "associated_phase_count"
        ),
        "quality_used_station_count": calidad.get("used_station_count"),
        "quality_associated_station_count": calidad.get(
            "associated_station_count"
        ),
        "quality_depth_phase_count": calidad.get("depth_phase_count"),
        "quality_standard_error": calidad.get("standard_error"),
        "quality_azimuthal_gap": calidad.get("azimuthal_gap"),
        "quality_secondary_azimuthal_gap": calidad.get(
            "secondary_azimuthal_gap"
        ),
        "quality_ground_truth_level": calidad.get("ground_truth_level"),
        "quality_minimum_distance_km": calidad.get("minimum_distance_km"),
        "quality_maximum_distance_km": calidad.get("maximum_distance_km"),
        "quality_median_distance_km": calidad.get("median_distance_km"),
        "unc_source": incertidumbre.get("source"),
        "unc_derived": incertidumbre.get("derived"),
    }
    for nombre in ("time", "latitude", "longitude", "depth"):
        datos = incertidumbre.get(nombre) or {}
        for clave in ("value", "lower", "upper", "confidence"):
            fila[f"unc_{nombre}_{clave}"] = datos.get(clave)
    horizontal = incertidumbre.get("horizontal") or {}
    fila["unc_horizontal_value"] = horizontal.get("value")
    fila["unc_horizontal_min"] = horizontal.get("min")
    fila["unc_horizontal_max"] = horizontal.get("max")
    fila["unc_horizontal_azimuth_max"] = horizontal.get("azimuth_max")
    elipse = incertidumbre.get("ellipse") or {}
    for clave in (
        "semimajor",
        "semiminor",
        "semiintermediate",
        "plunge",
        "azimuth",
        "rotation",
    ):
        fila[f"unc_ellipse_{clave}"] = elipse.get(clave)
    fila["unc_preferred_description"] = incertidumbre.get(
        "preferred_description"
    )
    fila["unc_confidence_level"] = incertidumbre.get("confidence_level")
    fila["origin_source"] = metadatos.get("source")
    fila["origin_derived"] = metadatos.get("derived")
    fila["origin_time_us"] = metadatos.get("origin_time_us")
    fila["origin_type"] = metadatos.get("type")
    fila["origin_evaluation_mode"] = metadatos.get("evaluation_mode")
    fila["origin_method_id"] = metadatos.get("method_id")
    fila["origin_earth_model_id"] = metadatos.get("earth_model_id")
    fila["origin_depth_type"] = metadatos.get("depth_type")
    fila.update(bloque("magnitude", magnitud))
    return fila


def _distancia_calculada(arribo: dict, evento: dict | None) -> float | None:
    if evento is None:
        return None
    lat_evento = _numero(evento.get("latitude"))
    lon_evento = _numero(evento.get("longitude"))
    lat_estacion = _numero(arribo.get("station_latitude"))
    lon_estacion = _numero(arribo.get("station_longitude"))
    if None in (lat_evento, lon_evento, lat_estacion, lon_estacion):
        return None
    return distancia_km(
        lat_evento, lon_evento, lat_estacion, lon_estacion
    )


def _aplanar_arribo(arribo: dict, evento: dict | None) -> dict:
    fila = {clave: arribo.get(clave) for clave in CABECERA_ARRIBOS}
    fila["distance_km_calc"] = _distancia_calculada(arribo, evento)
    return fila


def _resumen_estaciones(arribos, eventos: dict[str, dict]) -> list[dict]:
    resumen: dict[tuple, dict] = {}
    for arribo in arribos:
        clave = (
            arribo.get("source_id") or "",
            arribo.get("network") or "",
            arribo.get("station") or "",
            arribo.get("location") or "",
            arribo.get("channel") or "",
        )
        datos = resumen.setdefault(
            clave,
            {
                "source_id": clave[0],
                "network": clave[1],
                "station": clave[2],
                "location": clave[3],
                "channel": clave[4],
                "associated_phases": 0,
                "used_phases": 0,
                "residual_count": 0,
                "residual_suma": 0.0,
                "residual_suma_cuadrados": 0.0,
                "residual_max_abs": 0.0,
                "distance_min_km": None,
                "distance_max_km": None,
                "azimuth_suma": 0.0,
                "azimuth_count": 0,
                "used_in_solution": False,
                "pick_authors": set(),
            },
        )
        datos["associated_phases"] += 1
        if arribo.get("is_used_in_solution"):
            datos["used_phases"] += 1
            datos["used_in_solution"] = True
        residual = _numero(arribo.get("residual"))
        if residual is not None:
            datos["residual_count"] += 1
            datos["residual_suma"] += residual
            datos["residual_suma_cuadrados"] += residual * residual
            datos["residual_max_abs"] = max(
                datos["residual_max_abs"], abs(residual)
            )
        distancia = _distancia_calculada(
            arribo, eventos.get(arribo.get("event_id") or "")
        )
        if distancia is not None:
            minimo = datos["distance_min_km"]
            maximo = datos["distance_max_km"]
            datos["distance_min_km"] = (
                distancia if minimo is None else min(minimo, distancia)
            )
            datos["distance_max_km"] = (
                distancia if maximo is None else max(maximo, distancia)
            )
        azimut = _numero(arribo.get("azimuth"))
        if azimut is not None:
            datos["azimuth_suma"] += azimut
            datos["azimuth_count"] += 1
        autor = str(arribo.get("pick_author") or "").strip()
        if autor:
            datos["pick_authors"].add(autor)

    filas = []
    for clave in sorted(resumen):
        datos = resumen[clave]
        cantidad = datos["residual_count"]
        rms = (
            math.sqrt(datos["residual_suma_cuadrados"] / cantidad)
            if cantidad
            else None
        )
        medio = datos["residual_suma"] / cantidad if cantidad else None
        azimut_medio = (
            datos["azimuth_suma"] / datos["azimuth_count"]
            if datos["azimuth_count"]
            else None
        )
        filas.append(
            {
                "source_id": datos["source_id"],
                "network": datos["network"],
                "station": datos["station"],
                "location": datos["location"],
                "channel": datos["channel"],
                "associated_phases": datos["associated_phases"],
                "used_phases": datos["used_phases"],
                "residual_count": cantidad,
                "residual_rms_s": rms,
                "residual_mean_s": medio,
                "residual_max_abs_s": (
                    datos["residual_max_abs"] if cantidad else None
                ),
                "distance_min_km": datos["distance_min_km"],
                "distance_max_km": datos["distance_max_km"],
                "azimuth_mean_deg": _redondear_azimut(azimut_medio),
                "used_in_solution": datos["used_in_solution"],
                "pick_authors": ";".join(sorted(datos["pick_authors"])),
                "derived": True,
            }
        )
    return filas


def _redondear_azimut(valor):
    return None if valor is None else round(valor, 3)


def _escribir_csv(zf: zipfile.ZipFile, nombre: str, cabecera, filas) -> int:
    total = 0
    with zf.open(nombre, "w") as bruto:
        with io.TextIOWrapper(bruto, encoding="utf-8", newline="") as texto:
            escritor = csv.writer(texto)
            escritor.writerow(cabecera)
            for fila in filas:
                escritor.writerow([_celda(fila.get(clave)) for clave in cabecera])
                total += 1
    return total


def _leeme(fuente: str, job, totales: dict) -> str:
    return "\n".join(
        [
            "Catálogo completo extraído de RCS Web",
            "",
            f"Trabajo: {job.id}",
            f"Fuente: {fuente}",
            f"Período: {job.inicio14} → {job.fin14}",
            f"Generado: {datetime.now(UTC).isoformat()}",
            f"Esquema canónico: {SCHEMA_VERSION}",
            "",
            "Archivos:",
            "- eventos.csv: eventos con calidad, incertidumbres y metadatos.",
            "- arribos.csv: todos los arribos de la fuente.",
            "- estaciones_resumen.csv: RMS, conteos, distancias y azimut por estación.",
            "",
            "Unidades:",
            "- event_time: UTC.",
            "- origin_time_us: microsegundos.",
            "- depth_km y quality_*_distance_km: kilómetros.",
            "- residual: segundos.",
            "- distance_km: valor nativo de la fuente (SeisComp lo entrega en grados).",
            "- distance_km_calc: kilómetros calculados desde coordenadas.",
            "- azimuth y unc_horizontal_azimuth_max: grados.",
            "- unc_*_confidence: nivel de confianza 0–1.",
            "",
            "Procedencia:",
            "- quality_source, unc_source, origin_source y magnitude_source indican la fuente.",
            "- derived=False significa dato directo; derived=True, dato calculado.",
            "- estaciones_resumen.csv siempre es derived=True.",
            "",
            "Los bloques de calidad están vacíos cuando la fuente no los proporciona.",
            f"Eventos: {totales.get('eventos', 0)} · "
            f"arribos: {totales.get('arribos', 0)} · "
            f"estaciones: {totales.get('estaciones', 0)}",
        ]
    ) + "\n"


def generar(job, fuente: str = "seiscomp") -> tuple[Path, dict]:
    """Genera el ZIP y devuelve (ruta, totales)."""
    fuente = str(fuente or "").strip()
    if fuente not in FUENTES_HABILITADAS:
        raise CatalogoCompletoError(
            "En esta etapa el catálogo completo solo está disponible "
            "para SeisComp."
        )
    disponibles = {source.kind for source in job.sources}
    if fuente not in disponibles:
        raise CatalogoCompletoError(
            f"La fuente {fuente!r} no pertenece al trabajo."
        )
    workspace = ruta_workspace(job.id)
    eventos_ruta = canonical.ruta_canonica(workspace, fuente)
    arribos_ruta = canonical.ruta_arribos(workspace, fuente)
    if not eventos_ruta.is_file():
        raise CatalogoCompletoError(
            "El trabajo no tiene catálogo canónico para esa fuente."
        )

    eventos = list(_iter_jsonl(eventos_ruta))
    por_evento = {evento.get("event_id"): evento for evento in eventos}
    if not eventos:
        raise CatalogoCompletoError(
            "El catálogo canónico de la fuente está vacío."
        )

    destino = (
        workspace
        / "descargas"
        / f"catalogo_completo_{fuente}_{job.inicio14}_{job.fin14}.zip"
    )
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name(destino.name + ".tmp")

    resumen = _resumen_estaciones(
        _iter_jsonl(arribos_ruta), por_evento
    )
    totales = {
        "eventos": len(eventos),
        "arribos": 0,
        "estaciones": len(resumen),
    }
    try:
        with zipfile.ZipFile(
            temporal, "w", compression=zipfile.ZIP_DEFLATED
        ) as zf:
            _escribir_csv(
                zf,
                "eventos.csv",
                CABECERA_EVENTOS,
                (_aplanar_evento(evento) for evento in eventos),
            )
            totales["arribos"] = _escribir_csv(
                zf,
                "arribos.csv",
                CABECERA_ARRIBOS,
                (
                    _aplanar_arribo(
                        arribo,
                        por_evento.get(arribo.get("event_id") or ""),
                    )
                    for arribo in _iter_jsonl(arribos_ruta)
                ),
            )
            _escribir_csv(
                zf,
                "estaciones_resumen.csv",
                CABECERA_ESTACIONES,
                resumen,
            )
            zf.writestr("LEEME.txt", _leeme(fuente, job, totales))
        os.replace(temporal, destino)
    finally:
        if temporal.exists():
            temporal.unlink()
    return destino, totales
