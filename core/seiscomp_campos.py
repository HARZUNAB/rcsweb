"""Columnas extendidas del catálogo crudo de SeisComp.

Se separan del exportador para que el conversor canónico pueda importarlas sin
depender de psycopg2. El orden de ``COLUMNAS_EXTENDIDAS`` debe coincidir con el
orden de alias del SELECT de ``exporta_ventana_seiscomp.py``.
"""

from __future__ import annotations

COLUMNAS_EXTENDIDAS = (
    "origin_time_us",
    # Valores sin redondear; ``fases``, ``rms`` y ``azgap`` se mantienen por
    # compatibilidad con el catálogo histórico.
    "standard_error",
    "azimuthal_gap",
    # Incertidumbre del origen
    "time_uncertainty",
    "time_lower_uncertainty",
    "time_upper_uncertainty",
    "time_confidence",
    "latitude_uncertainty",
    "latitude_lower_uncertainty",
    "latitude_upper_uncertainty",
    "latitude_confidence",
    "longitude_uncertainty",
    "longitude_lower_uncertainty",
    "longitude_upper_uncertainty",
    "longitude_confidence",
    "depth_uncertainty",
    "depth_lower_uncertainty",
    "depth_upper_uncertainty",
    "depth_confidence",
    # Incertidumbre horizontal y elipse
    "horizontal_uncertainty",
    "min_horizontal_uncertainty",
    "max_horizontal_uncertainty",
    "azimuth_max_horizontal_uncertainty",
    "ellipse_semimajor",
    "ellipse_semiminor",
    "ellipse_semiintermediate",
    "ellipse_plunge",
    "ellipse_azimuth",
    "ellipse_rotation",
    "uncertainty_preferred_description",
    "uncertainty_confidence",
    # OriginQuality
    "associated_phase_count",
    "used_station_count",
    "associated_station_count",
    "depth_phase_count",
    "secondary_azimuthal_gap",
    "ground_truth_level",
    "minimum_distance_deg",
    "maximum_distance_deg",
    "median_distance_deg",
    # Metadatos del origen
    "origin_type",
    "evaluation_mode",
    "method_id",
    "earth_model_id",
    "depth_type",
    # Magnitud
    "magnitude_uncertainty",
    "magnitude_lower_uncertainty",
    "magnitude_upper_uncertainty",
    "magnitude_confidence",
    "magnitude_station_count",
    "magnitude_azimuthal_gap",
    "magnitude_status",
    "magnitude_method_id",
)

COLUMNAS_DERIVADAS = (
    "minimum_distance_km",
    "maximum_distance_km",
    "median_distance_km",
)

# Columnas del evento que el conversor necesita conservar para el canónico.
COLUMNAS_CALIDAD = ("fases", "rms", "azgap")

# ``estatus`` se conserva para que el bloque origin_metadata pueda llevar el
# estado de evaluación del origen.
COLUMNAS_CONVERTIDAS = (
    COLUMNAS_CALIDAD
    + ("estatus",)
    + COLUMNAS_EXTENDIDAS
    + COLUMNAS_DERIVADAS
)
