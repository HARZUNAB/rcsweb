"""Modelos de datos de rcsweb.

En la etapa 1 los resultados del pipeline siguen viviendo en CSV/JSON dentro de
``workspace/<job>``; estas tablas guardan estado, metadatos y auditoría.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from flask_login import UserMixin
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db, login_manager


def utcnow() -> datetime:
    return datetime.now(UTC)


def nuevo_uuid() -> str:
    return str(uuid.uuid4())


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="analista")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def is_active(self) -> bool:  # Flask-Login
        return self.active

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return f"<User {self.username}>"


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    return db.session.get(User, int(user_id))


class CatalogRequest(db.Model):
    """Solicitud de adquisición de catálogos (subida o SSH)."""

    __tablename__ = "catalog_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuevo_uuid)
    mode: Mapped[str] = mapped_column(String(16), default="upload")
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    current_step: Mapped[str | None] = mapped_column(String(80))
    requested_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    server: Mapped[str | None] = mapped_column(String(255))
    remote_user: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)

    requested_by = relationship("User")
    files = relationship(
        "CatalogRequestFile",
        back_populates="request",
        cascade="all, delete-orphan",
    )

    @property
    def inicio14(self) -> str:
        return self.period_start.strftime("%Y%m%d%H%M%S") if self.period_start else ""

    @property
    def fin14(self) -> str:
        return self.period_end.strftime("%Y%m%d%H%M%S") if self.period_end else ""

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CatalogRequest {self.id} {self.mode} {self.status}>"


class CatalogRequestFile(db.Model):
    __tablename__ = "catalog_request_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[str] = mapped_column(
        ForeignKey("catalog_requests.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    format: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    stored_path: Mapped[str | None] = mapped_column(String(255))
    original_name: Mapped[str | None] = mapped_column(String(255))
    size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    message: Mapped[str | None] = mapped_column(Text)

    request = relationship("CatalogRequest", back_populates="files")


class Job(db.Model):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=nuevo_uuid)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    current_step: Mapped[str | None] = mapped_column(String(80))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(16), default="upload")
    catalog_request_id: Mapped[str | None] = mapped_column(
        ForeignKey("catalog_requests.id", ondelete="SET NULL")
    )

    created_by = relationship("User", foreign_keys=[created_by_id])
    catalog_request = relationship("CatalogRequest")
    files = relationship("JobFile", back_populates="job", cascade="all, delete-orphan")
    steps = relationship("JobStep", back_populates="job", cascade="all, delete-orphan")
    artifacts = relationship("JobArtifact", back_populates="job", cascade="all, delete-orphan")
    sources = relationship("JobSource", back_populates="job", cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Job {self.id} {self.status}>"

    @property
    def inicio14(self) -> str:
        return self.period_start.strftime("%Y%m%d%H%M%S") if self.period_start else ""

    @property
    def fin14(self) -> str:
        return self.period_end.strftime("%Y%m%d%H%M%S") if self.period_end else ""

    @property
    def activo(self) -> bool:
        return self.status in ("queued", "running", "cancelling")

    @property
    def duracion_seg(self) -> int | None:
        if not self.started_at:
            return None
        inicio = self.started_at
        fin = self.finished_at or utcnow()
        if inicio.tzinfo is None:
            inicio = inicio.replace(tzinfo=UTC)
        if fin.tzinfo is None:
            fin = fin.replace(tzinfo=UTC)
        return max(0, int((fin - inicio).total_seconds()))


class JobFile(db.Model):
    __tablename__ = "job_files"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # seisan | eventquery | seiscomp
    original_name: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(255))
    size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    job = relationship("Job", back_populates="files")


class JobSource(db.Model):
    """Fuente de catálogo seleccionada para un trabajo."""

    __tablename__ = "job_sources"
    __table_args__ = (UniqueConstraint("job_id", "kind", name="uq_job_sources_job_kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    alias: Mapped[str] = mapped_column(String(80), default="")
    format: Mapped[str] = mapped_column(String(32), default="")
    role: Mapped[str] = mapped_column(String(24), default="local_secundaria")
    priority: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="ok")
    message: Mapped[str | None] = mapped_column(Text)
    capabilities: Mapped[dict | None] = mapped_column(JSON)
    catalog_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("catalog_request_files.id", ondelete="SET NULL")
    )

    job = relationship("Job", back_populates="sources")
    catalog_file = relationship("CatalogRequestFile")

    @property
    def format_efectivo(self) -> str:
        return self.format or self.kind

    @property
    def alias_mostrado(self) -> str:
        return self.alias or self.kind

    @property
    def capacidades(self) -> set[str]:
        return set(self.capabilities or ())


class CatalogEvent(db.Model):
    """Evento del catálogo canónico de una fuente."""

    __tablename__ = "catalog_events"
    __table_args__ = (
        UniqueConstraint(
            "job_id", "source_id", "event_id", name="uq_catalog_events_job_source_event"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    event_id: Mapped[str] = mapped_column(String(128), index=True)
    event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    depth_km: Mapped[float | None] = mapped_column(Float)
    magnitude: Mapped[float | None] = mapped_column(Float)
    magnitude_type: Mapped[str] = mapped_column(String(16), default="")
    agency: Mapped[str] = mapped_column(String(80), default="")
    analyst: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(32), default="")
    is_preferred: Mapped[bool] = mapped_column(Boolean, default=True)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    raw: Mapped[dict | None] = mapped_column(JSON)


class Station(db.Model):
    """Inventario de estaciones/canales aportado por una fuente."""

    __tablename__ = "stations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    network: Mapped[str] = mapped_column(String(16), default="")
    station: Mapped[str] = mapped_column(String(16), default="")
    location: Mapped[str] = mapped_column(String(16), default="")
    channel: Mapped[str] = mapped_column(String(16), default="")
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    elevation_m: Mapped[float | None] = mapped_column(Float)
    depth_m: Mapped[float | None] = mapped_column(Float)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sample_rate: Mapped[float | None] = mapped_column(Float)
    response: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="")


class Arrival(db.Model):
    """Arribo/pick de un origen, con estado manual/automático."""

    __tablename__ = "arrivals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    event_id: Mapped[str] = mapped_column(String(128), index=True)
    origin_id: Mapped[str] = mapped_column(String(128), default="")
    network: Mapped[str] = mapped_column(String(16), default="")
    station: Mapped[str] = mapped_column(String(16), default="")
    location: Mapped[str] = mapped_column(String(16), default="")
    channel: Mapped[str] = mapped_column(String(16), default="")
    phase: Mapped[str] = mapped_column(String(16), default="")
    pick_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pick_status: Mapped[str] = mapped_column(String(16), default="")
    is_used_in_solution: Mapped[bool | None] = mapped_column(Boolean)
    weight: Mapped[float | None] = mapped_column(Float)
    polarity: Mapped[str] = mapped_column(String(16), default="")
    residual: Mapped[float | None] = mapped_column(Float)
    distance_km: Mapped[float | None] = mapped_column(Float)
    azimuth: Mapped[float | None] = mapped_column(Float)
    snr: Mapped[float | None] = mapped_column(Float)
    qc: Mapped[str] = mapped_column(String(32), default="")
    picker_probability: Mapped[float | None] = mapped_column(Float)


class WaveformAvailability(db.Model):
    """Resultado del chequeo de formas de onda por estación/evento."""

    __tablename__ = "waveform_availability"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    event_id: Mapped[str] = mapped_column(String(128), index=True)
    network: Mapped[str] = mapped_column(String(16), default="")
    station: Mapped[str] = mapped_column(String(16), default="")
    location: Mapped[str] = mapped_column(String(16), default="")
    channel: Mapped[str] = mapped_column(String(16), default="")
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="not_checked")
    source: Mapped[str] = mapped_column(String(32), default="")
    coverage_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    coverage_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class JobStep(db.Model):
    __tablename__ = "job_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    orden: Mapped[int] = mapped_column(Integer)
    script: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    exit_code: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    log_path: Mapped[str | None] = mapped_column(String(255))

    job = relationship("Job", back_populates="steps")

    @property
    def duracion_seg(self) -> int | None:
        if not self.started_at:
            return None
        inicio = self.started_at
        fin = self.finished_at or utcnow()
        if inicio.tzinfo is None:
            inicio = inicio.replace(tzinfo=UTC)
        if fin.tzinfo is None:
            fin = fin.replace(tzinfo=UTC)
        return max(0, int((fin - inicio).total_seconds()))


class JobArtifact(db.Model):
    __tablename__ = "job_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    tipo: Mapped[str] = mapped_column(String(48))
    ruta: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str | None] = mapped_column(String(80))
    size: Mapped[int] = mapped_column(Integer, default=0)

    job = relationship("Job", back_populates="artifacts")


class AuditLog(db.Model):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity: Mapped[str | None] = mapped_column(String(80))
    meta: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    user = relationship("User")
