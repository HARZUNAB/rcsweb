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
FUENTES_HABILITADAS = frozenset({"seiscomp", "central", "seisan"})


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
    "quality_derived_fields",
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
    "unc_derived_fields",
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
    "unc_error_ellipse",
    "origin_source",
    "origin_derived",
    "origin_derived_fields",
    "origin_time_us",
    "origin_type",
    "origin_evaluation_mode",
    "origin_method_id",
    "origin_earth_model_id",
    "origin_depth_type",
    "origin_evaluation_status",
    "origin_software",
    "origin_velocity_model",
    "magnitude_source",
    "magnitude_derived",
    "magnitude_derived_fields",
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
    "pick_uncertainty",
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
    "uncertainty_count",
    "uncertainty_rms_s",
    "uncertainty_mean_s",
    "uncertainty_max_abs_s",
    "distance_min_km",
    "distance_max_km",
    "azimuth_mean_deg",
    "used_in_solution",
    "pick_authors",
    "derived",
)

ETIQUETAS_EVENTO = {
    "source_id": "Fuente",
    "event_id": "Evento",
    "source_event_id": "ID en la fuente",
    "origin_id": "Origen",
    "database": "Base de datos",
    "event_time": "Fecha y hora",
    "latitude": "Latitud",
    "longitude": "Longitud",
    "depth_km": "Profundidad (km)",
    "magnitude": "Magnitud",
    "magnitude_type": "Tipo de magnitud",
    "agency": "Agencia",
    "analyst": "Analista",
    "status": "Estado",
    "revision": "Revisión",
    "is_preferred": "Preferida",
    "is_published": "Publicada",
    "raw_index": "Índice crudo",
    "quality_source": "Fuente de calidad",
    "quality_derived": "Calidad derivada",
    "quality_derived_fields": "Campos derivados",
    "quality_used_phase_count": "Fases usadas",
    "quality_associated_phase_count": "Fases asociadas",
    "quality_used_station_count": "Estaciones usadas",
    "quality_associated_station_count": "Estaciones asociadas",
    "quality_depth_phase_count": "Fases de profundidad",
    "quality_standard_error": "Error estándar (s)",
    "quality_azimuthal_gap": "Azimutal gap (°)",
    "quality_secondary_azimuthal_gap": "Azimutal gap secundario (°)",
    "quality_ground_truth_level": "Nivel ground truth",
    "quality_minimum_distance_km": "Distancia mínima (km)",
    "quality_maximum_distance_km": "Distancia máxima (km)",
    "quality_median_distance_km": "Distancia mediana (km)",
    "unc_source": "Fuente de incertidumbre",
    "unc_derived": "Incertidumbre derivada",
    "unc_derived_fields": "Campos derivados",
    "unc_time_value": "Incertidumbre tiempo (s)",
    "unc_time_lower": "Tiempo inferior",
    "unc_time_upper": "Tiempo superior",
    "unc_time_confidence": "Confianza tiempo",
    "unc_latitude_value": "Incertidumbre latitud",
    "unc_latitude_lower": "Latitud inferior",
    "unc_latitude_upper": "Latitud superior",
    "unc_latitude_confidence": "Confianza latitud",
    "unc_longitude_value": "Incertidumbre longitud",
    "unc_longitude_lower": "Longitud inferior",
    "unc_longitude_upper": "Longitud superior",
    "unc_longitude_confidence": "Confianza longitud",
    "unc_depth_value": "Incertidumbre profundidad",
    "unc_depth_lower": "Profundidad inferior",
    "unc_depth_upper": "Profundidad superior",
    "unc_depth_confidence": "Confianza profundidad",
    "unc_horizontal_value": "Incertidumbre horizontal",
    "unc_horizontal_min": "Horizontal mínima",
    "unc_horizontal_max": "Horizontal máxima",
    "unc_horizontal_azimuth_max": "Azimut horizontal máximo",
    "unc_ellipse_semimajor": "Elipse semieje mayor",
    "unc_ellipse_semiminor": "Elipse semieje menor",
    "unc_ellipse_semiintermediate": "Elipse semieje intermedio",
    "unc_ellipse_plunge": "Elipse inclinación",
    "unc_ellipse_azimuth": "Elipse azimut",
    "unc_ellipse_rotation": "Elipse rotación",
    "unc_preferred_description": "Descripción preferida",
    "unc_confidence_level": "Nivel de confianza",
    "unc_error_ellipse": "Elipse de error",
    "origin_source": "Fuente del origen",
    "origin_derived": "Origen derivado",
    "origin_derived_fields": "Campos derivados",
    "origin_time_us": "Tiempo de origen (µs)",
    "origin_type": "Tipo de origen",
    "origin_evaluation_mode": "Modo de evaluación",
    "origin_method_id": "Método",
    "origin_earth_model_id": "Modelo terrestre",
    "origin_depth_type": "Tipo de profundidad",
    "origin_evaluation_status": "Estado de evaluación",
    "origin_software": "Software",
    "origin_velocity_model": "Modelo de velocidades",
    "magnitude_source": "Fuente de magnitud",
    "magnitude_derived": "Magnitud derivada",
    "magnitude_derived_fields": "Campos derivados",
    "magnitude_uncertainty": "Incertidumbre magnitud",
    "magnitude_lower_uncertainty": "Magnitud inferior",
    "magnitude_upper_uncertainty": "Magnitud superior",
    "magnitude_confidence": "Confianza magnitud",
    "magnitude_station_count": "Estaciones de la magnitud",
    "magnitude_azimuthal_gap": "Azimutal gap de magnitud",
    "magnitude_status": "Estado de magnitud",
    "magnitude_method_id": "Método de magnitud",
}

ETIQUETAS_ARRIBO = {
    "source_id": "Fuente",
    "event_id": "Evento",
    "source_event_id": "ID en la fuente",
    "origin_id": "Origen",
    "pick_id": "Pick",
    "network": "Red",
    "station": "Estación",
    "location": "Localización",
    "channel": "Canal",
    "phase": "Fase",
    "pick_time": "Hora del pick",
    "pick_status": "Modo del pick",
    "is_used_in_solution": "Usada",
    "weight": "Peso",
    "polarity": "Polaridad",
    "residual": "Residual (s)",
    "pick_uncertainty": "Incertidumbre del pick (s)",
    "distance_km": "Distancia nativa",
    "distance_km_calc": "Distancia calculada (km)",
    "azimuth": "Azimut (°)",
    "snr": "SNR",
    "qc": "QC",
    "picker_probability": "Probabilidad",
    "time_correction_s": "Corrección (s)",
    "pick_author": "Autor del pick",
    "pick_agency": "Agencia del pick",
    "pick_method": "Método del pick",
    "station_magnitude": "Magnitud de estación",
    "station_magnitude_type": "Tipo magnitud estación",
    "has_station_magnitude": "Tiene magnitud",
    "station_magnitude_residual": "Residual de magnitud",
    "station_latitude": "Latitud estación",
    "station_longitude": "Longitud estación",
    "station_elevation_m": "Elevación estación (m)",
    "station_place": "Lugar estación",
    "station_country": "País estación",
    "database": "Base de datos",
}

ETIQUETAS_ESTACION = {
    "source_id": "Fuente",
    "network": "Red",
    "station": "Estación",
    "location": "Localización",
    "channel": "Canal",
    "associated_phases": "Fases asociadas",
    "used_phases": "Fases usadas",
    "residual_count": "Residuales",
    "residual_rms_s": "RMS residual (s)",
    "residual_mean_s": "Residual medio (s)",
    "residual_max_abs_s": "Residual máx. abs. (s)",
    "uncertainty_count": "Incertidumbres",
    "uncertainty_rms_s": "RMS incertidumbre (s)",
    "uncertainty_mean_s": "Incertidumbre media (s)",
    "uncertainty_max_abs_s": "Incertidumbre máx. abs. (s)",
    "distance_min_km": "Distancia mínima (km)",
    "distance_max_km": "Distancia máxima (km)",
    "azimuth_mean_deg": "Azimut medio (°)",
    "used_in_solution": "Usada",
    "pick_authors": "Autores de pick",
    "derived": "Derivada",
}

GRUPOS_EVENTO_RESUMEN = (
    (
        "Evento",
        (
            "event_id",
            "event_time",
            "latitude",
            "longitude",
            "depth_km",
            "magnitude",
            "magnitude_type",
            "analyst",
            "status",
        ),
    ),
    (
        "Calidad",
        (
            "quality_used_phase_count",
            "quality_associated_phase_count",
            "quality_used_station_count",
            "quality_associated_station_count",
            "quality_standard_error",
            "quality_azimuthal_gap",
            "quality_minimum_distance_km",
            "quality_maximum_distance_km",
        ),
    ),
    (
        "Incertidumbre",
        (
            "unc_time_value",
            "unc_latitude_value",
            "unc_longitude_value",
            "unc_depth_value",
            "unc_horizontal_value",
        ),
    ),
    (
        "Origen",
        (
            "origin_time_us",
            "origin_evaluation_status",
            "origin_software",
            "origin_velocity_model",
        ),
    ),
    (
        "Magnitud",
        (
            "magnitude_uncertainty",
            "magnitude_station_count",
            "magnitude_method_id",
        ),
    ),
)


def _grupos_evento_ficha():
    grupos: dict[str, list[str]] = {
        "Evento": [],
        "Calidad": [],
        "Incertidumbre": [],
        "Origen": [],
        "Magnitud": [],
    }
    for clave in CABECERA_EVENTOS:
        if clave.startswith("quality_"):
            grupos["Calidad"].append(clave)
        elif clave.startswith("unc_"):
            grupos["Incertidumbre"].append(clave)
        elif clave.startswith("origin_"):
            grupos["Origen"].append(clave)
        elif clave.startswith("magnitude_"):
            grupos["Magnitud"].append(clave)
        else:
            grupos["Evento"].append(clave)
    return tuple((nombre, tuple(claves)) for nombre, claves in grupos.items())


GRUPOS_EVENTO_FICHA = _grupos_evento_ficha()


def etiqueta_evento(clave: str) -> str:
    return ETIQUETAS_EVENTO.get(
        clave, clave.replace("_", " ").capitalize()
    )


def etiqueta_arribo(clave: str) -> str:
    return ETIQUETAS_ARRIBO.get(
        clave, clave.replace("_", " ").capitalize()
    )


def etiqueta_estacion(clave: str) -> str:
    return ETIQUETAS_ESTACION.get(
        clave, clave.replace("_", " ").capitalize()
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


def _iter_arribos(ruta: Path, ids: set[str] | None):
    for arribo in _iter_jsonl(ruta):
        if ids is None or arribo.get("event_id") in ids:
            yield arribo


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


def _derivados(valor) -> str:
    if not valor:
        return ""
    if isinstance(valor, str):
        return valor
    return ";".join(str(item) for item in valor)


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
        "quality_derived_fields": _derivados(
            calidad.get("derived_fields")
        ),
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
        "unc_derived_fields": _derivados(
            incertidumbre.get("derived_fields")
        ),
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
    fila["unc_error_ellipse"] = incertidumbre.get("error_ellipse")
    fila["origin_source"] = metadatos.get("source")
    fila["origin_derived"] = metadatos.get("derived")
    fila["origin_derived_fields"] = _derivados(
        metadatos.get("derived_fields")
    )
    fila["origin_time_us"] = metadatos.get("origin_time_us")
    fila["origin_type"] = metadatos.get("type")
    fila["origin_evaluation_mode"] = metadatos.get("evaluation_mode")
    fila["origin_method_id"] = metadatos.get("method_id")
    fila["origin_earth_model_id"] = metadatos.get("earth_model_id")
    fila["origin_depth_type"] = metadatos.get("depth_type")
    fila["origin_evaluation_status"] = metadatos.get(
        "evaluation_status"
    )
    fila["origin_software"] = metadatos.get("software")
    fila["origin_velocity_model"] = metadatos.get("velocity_model")
    fila.update(bloque("magnitude", magnitud))
    fila["magnitude_derived_fields"] = _derivados(
        magnitud.get("derived_fields")
    )
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
                "uncertainty_count": 0,
                "uncertainty_suma": 0.0,
                "uncertainty_suma_cuadrados": 0.0,
                "uncertainty_max_abs": 0.0,
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
        incertidumbre = _numero(arribo.get("pick_uncertainty"))
        if incertidumbre is not None:
            datos["uncertainty_count"] += 1
            datos["uncertainty_suma"] += incertidumbre
            datos["uncertainty_suma_cuadrados"] += (
                incertidumbre * incertidumbre
            )
            datos["uncertainty_max_abs"] = max(
                datos["uncertainty_max_abs"], abs(incertidumbre)
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
        cantidad_inc = datos["uncertainty_count"]
        rms_inc = (
            math.sqrt(
                datos["uncertainty_suma_cuadrados"] / cantidad_inc
            )
            if cantidad_inc
            else None
        )
        medio_inc = (
            datos["uncertainty_suma"] / cantidad_inc
            if cantidad_inc
            else None
        )
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
                "uncertainty_count": cantidad_inc,
                "uncertainty_rms_s": rms_inc,
                "uncertainty_mean_s": medio_inc,
                "uncertainty_max_abs_s": (
                    datos["uncertainty_max_abs"] if cantidad_inc else None
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


def _leeme(
    fuente: str, job, totales: dict, filtros_texto: str = ""
) -> str:
    return "\n".join(
        [
            "Catálogo completo extraído de RCS Web",
            "",
            f"Trabajo: {job.id}",
            f"Fuente: {fuente}",
            f"Período: {job.inicio14} → {job.fin14}",
            f"Generado: {datetime.now(UTC).isoformat()}",
            f"Esquema canónico: {SCHEMA_VERSION}",
            f"Filtros: {filtros_texto or 'Sin filtros'}",
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
            "- pick_uncertainty: incertidumbre del pick, en segundos. Central "
            "no trae residual separado.",
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


def cargar_eventos(
    job, fuente: str, ids: set[str] | None = None
) -> list[dict]:
    workspace = ruta_workspace(job.id)
    ruta = canonical.ruta_canonica(workspace, fuente)
    eventos = list(_iter_jsonl(ruta))
    if ids is not None:
        eventos = [
            evento for evento in eventos if evento.get("event_id") in ids
        ]
    return eventos


def _pasa_filtro_arribo(arribo: dict, filtros: dict | None) -> bool:
    if not filtros:
        return True
    evento = str(filtros.get("evento") or "").strip()
    if evento and str(arribo.get("event_id") or "") != evento:
        if str(arribo.get("source_event_id") or "") != evento:
            return False
    estacion = str(filtros.get("estacion") or "").strip().upper()
    if estacion and estacion not in str(arribo.get("station") or "").upper():
        return False
    fase = str(filtros.get("fase") or "").strip().upper()
    if fase and str(arribo.get("phase") or "").upper() != fase:
        return False
    usada = str(filtros.get("usada") or "").strip().lower()
    if usada in ("1", "true", "si", "sí"):
        if not arribo.get("is_used_in_solution"):
            return False
    elif usada in ("0", "false", "no"):
        if arribo.get("is_used_in_solution"):
            return False
    return True


def pagina_arribos(
    job,
    fuente: str,
    ids: set[str] | None,
    *,
    page: int = 1,
    per_page: int = 100,
    filtros: dict | None = None,
) -> tuple[int, list[dict]]:
    """Total filtrado y la página pedida, en una sola pasada."""
    inicio = max(0, (page - 1) * per_page)
    fin = inicio + per_page
    total = 0
    filas: list[dict] = []
    ruta = canonical.ruta_arribos(ruta_workspace(job.id), fuente)
    for arribo in _iter_arribos(ruta, ids):
        if not _pasa_filtro_arribo(arribo, filtros):
            continue
        total += 1
        if inicio < total <= fin:
            filas.append(arribo)
    return total, filas


def resumen_estaciones(
    job, fuente: str, ids: set[str] | None
) -> list[dict]:
    eventos = cargar_eventos(job, fuente, ids)
    por_evento = {evento.get("event_id"): evento for evento in eventos}
    ruta = canonical.ruta_arribos(ruta_workspace(job.id), fuente)
    return _resumen_estaciones(_iter_arribos(ruta, ids), por_evento)


def texto_leeme(
    job,
    fuente: str,
    totales: dict,
    filtros_texto: str = "",
) -> str:
    return _leeme(fuente, job, totales, filtros_texto)


def generar(
    job,
    fuente: str = "seiscomp",
    *,
    ids: set[str] | None = None,
    filtros_texto: str = "",
    destino: Path | None = None,
) -> tuple[Path, dict]:
    """Genera el ZIP y devuelve (ruta, totales).

    ``ids`` limita la exportación a los eventos canónicos indicados. Es lo que
    usa la página de Catálogos para respetar los filtros actuales.
    """
    fuente = str(fuente or "").strip()
    if fuente not in FUENTES_HABILITADAS:
        raise CatalogoCompletoError(
            "El catálogo completo solo está disponible para SeisComp, "
            "Central o Seisan."
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
    if ids is not None:
        eventos = [
            evento for evento in eventos if evento.get("event_id") in ids
        ]
    por_evento = {evento.get("event_id"): evento for evento in eventos}
    if not eventos:
        raise CatalogoCompletoError(
            "No hay eventos para los filtros actuales."
        )

    if destino is None:
        destino = (
            workspace
            / "descargas"
            / f"catalogo_completo_{fuente}_{job.inicio14}_{job.fin14}.zip"
        )
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_name(destino.name + ".tmp")

    resumen = _resumen_estaciones(
        _iter_arribos(arribos_ruta, ids), por_evento
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
                    for arribo in _iter_arribos(arribos_ruta, ids)
                ),
            )
            _escribir_csv(
                zf,
                "estaciones_resumen.csv",
                CABECERA_ESTACIONES,
                resumen,
            )
            zf.writestr(
                "LEEME.txt",
                _leeme(fuente, job, totales, filtros_texto),
            )
        os.replace(temporal, destino)
    finally:
        if temporal.exists():
            temporal.unlink()
    return destino, totales
