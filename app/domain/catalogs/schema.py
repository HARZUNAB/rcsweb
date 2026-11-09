"""Contrato canónico de catálogos.

La app trabaja con este contrato y no con los formatos de cada fuente. Las
extensiones son opcionales: una fuente puede aportar solo eventos, o también
estaciones, arribos y disponibilidad de formas de onda.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

SCHEMA_VERSION = "1.2"

CAPACIDADES = {
    "eventos",
    "origenes",
    "magnitudes",
    "arribos",
    "inventario",
    "disponibilidad_ondas",
    "tensores",
    "excluidos",
    "percibidos",
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
    # Identidad de la fila en el archivo crudo. Permite enlazar los arribos y
    # las estaciones sin arribos, que traen ``id_evento`` e ``id_origen``,
    # sin depender de una tabla relacional.
    source_event_id: str = ""
    origin_id: str = ""
    # Base de datos de SeisComp de la que salió la solución. Se usa para
    # recalcular el inventario de estaciones al ampliar el radio.
    database: str = ""
    raw_index: int | None = None
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
    # Identidad en la fuente. ``event_id`` es el id canónico del evento y
    # ``source_event_id`` el identificador que trae el archivo de arribos.
    source_event_id: str = ""
    pick_id: str = ""
    time_correction_s: float | None = None
    pick_author: str = ""
    pick_agency: str = ""
    pick_method: str = ""
    station_magnitude: float | None = None
    station_magnitude_type: str = ""
    has_station_magnitude: str = ""
    station_magnitude_residual: float | None = None
    station_latitude: float | None = None
    station_longitude: float | None = None
    station_elevation_m: float | None = None
    station_place: str = ""
    station_country: str = ""
    database: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class EstacionSinArribosCanonica:
    """Estación del inventario que no tiene arribos en el evento revisado.

    No significa que no haya grabado: la exportación solo sabe qué estaciones
    estaban configuradas dentro del radio y no aparecen en la solución.
    """

    source_id: str
    event_id: str
    source_event_id: str
    origin_id: str
    network: str
    station: str
    location: str
    channel: str
    streams: str = ""
    stream_ids: str = ""
    distance_km: float | None = None
    station_latitude: float | None = None
    station_longitude: float | None = None
    station_elevation_m: float | None = None
    station_place: str = ""
    station_country: str = ""
    radio_km: float | None = None
    activity_window: int | None = None
    evidence: str = ""
    waveform_status: str = "NO_CONSULTADO"
    availability_source: str = ""
    coverage_from: str | None = None
    coverage_to: str | None = None
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


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


@dataclass
class TensorMomentoCanonico:
    """Tensor de momento y mecanismo focal de un origen.

    Las componentes y el momento escalar se normalizan a Nm cuando la unidad
    de origen es conocida. ``moment_units_original`` conserva la unidad tal como
    vino en la fuente.
    """

    source_id: str
    event_id: str
    origin_id: str
    tensor_id: str
    method: str = ""
    mechanism: str = ""
    strike1: float | None = None
    dip1: float | None = None
    rake1: float | None = None
    strike2: float | None = None
    dip2: float | None = None
    rake2: float | None = None
    m_rr: float | None = None
    m_tt: float | None = None
    m_pp: float | None = None
    m_rt: float | None = None
    m_rp: float | None = None
    m_tp: float | None = None
    scalar_moment: float | None = None
    moment_units: str = ""
    moment_units_original: str = ""
    moment_magnitude: float | None = None
    is_preferred: bool = False
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
