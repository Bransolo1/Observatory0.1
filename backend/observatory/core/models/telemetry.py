import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from observatory.core.models.base import Base, TenantMixin, TimestampMixin


class TelemetryConnection(Base, TenantMixin, TimestampMixin):
    """OAuth/API credentials for analytics platforms."""

    __tablename__ = "telemetry_connections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    platform: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # mixpanel, amplitude, posthog
    credentials: Mapped[dict] = mapped_column(JSONB, nullable=False)  # encrypted at rest
    config: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    is_active: Mapped[bool] = mapped_column(default=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_status: Mapped[str | None] = mapped_column(String(20), nullable=True)


class FunnelDefinition(Base, TenantMixin, TimestampMixin):
    """Configurable funnel definitions for tracking conversion flows."""

    __tablename__ = "funnel_definitions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    steps: Mapped[dict] = mapped_column(JSONB, nullable=False)  # ordered list of events
    product_area: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)


class TelemetryAggregate(Base, TenantMixin, TimestampMixin):
    """Daily rollups of telemetry metrics."""

    __tablename__ = "telemetry_aggregates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    metric_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    metric_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # funnel_step, retention, feature_usage, session
    metric_name: Mapped[str] = mapped_column(String(255), nullable=False)
    product_area: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Values
    value: Mapped[float] = mapped_column(Float, nullable=False)
    previous_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)

    # Context
    dimensions: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )  # segment, platform, etc.
    source_platform: Mapped[str] = mapped_column(String(50), nullable=False)


class FrictionSignal(Base, TenantMixin, TimestampMixin):
    """Detected friction points from telemetry analysis."""

    __tablename__ = "friction_signals"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    signal_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # drop_off, rage_click, slow_load, error_spike
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # low, medium, high, critical
    product_area: Mapped[str | None] = mapped_column(String(255), nullable=True)
    funnel_step: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Metrics
    current_rate: Mapped[float] = mapped_column(Float, nullable=False)
    baseline_rate: Mapped[float] = mapped_column(Float, nullable=False)
    deviation_score: Mapped[float] = mapped_column(Float, nullable=False)  # z-score or equivalent
    affected_users: Mapped[int] = mapped_column(Integer, default=0)

    # Context
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="active"
    )  # active, investigating, resolved, dismissed
