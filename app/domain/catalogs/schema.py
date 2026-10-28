"""Contrato canónico de catálogos.

La app trabaja con este contrato y no con los formatos de cada fuente. Las
extensiones son opcionales: una fuente puede aportar solo eventos, o también
estaciones, arribos y disponibilidad de formas de onda.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

SCHEMA_VERSION = "1.0"

CAPACIDADES = {
    "eventos",
    "origenes",
    "magnitudes",
    "arribos",
    "inventario",
    "disponibilidad_ondas",
    "excluidos",
}


@dataclass
class EventoCanonico:
    source_id: str
    event_id: str
    event_time: str | None
    latitude: float | None
    longitude: float | None
    depth_km: float | None
    magnitude: float | None
    magnitude_type: str = ""
    agency: str = ""
    analyst: str = ""
    status: str = ""
    is_preferred: bool = True
    is_published: bool = False
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EstacionCanonica:
    source_id: str
    network: str
    station: str
    location: str
    channel: str
    latitude: float | None
    longitude: float | None
    elevation_m: float | None = None
    depth_m: float | None = None
    start_time: str | None = None
    end_time: str | None = None
    sample_rate: float | None = None
    response: str = ""
    status: str = ""


@dataclass
class ArriboCanonico:
    source_id: str
    event_id: str
    origin_id: str
    network: str
    station: str
    location: str
    channel: str
    phase: str
    pick_time: str | None
    pick_status: str = ""  # manual | automatic
    is_used_in_solution: bool | None = None
    weight: float | None = None
    polarity: str = ""
    residual: float | None = None
    distance_km: float | None = None
    azimuth: float | None = None
    snr: float | None = None
    qc: str = ""
    picker_probability: float | None = None


@dataclass
class DisponibilidadOnda:
    source_id: str
    event_id: str
    network: str
    station: str
    location: str
    channel: str
    window_start: str | None
    window_end: str | None
    status: str = "not_checked"
    source: str = ""
    coverage_from: str | None = None
    coverage_to: str | None = None
    checked_at: str | None = None
    error: str = ""
