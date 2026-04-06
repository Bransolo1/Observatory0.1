import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from observatory.core.models.base import Base, TenantMixin, TimestampMixin


class Insight(Base, TenantMixin, TimestampMixin):
    """Synthesized insights from analysis engine — the core output of Observatory."""

    __tablename__ = "insights"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    insight_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # friction_report, competitive_change, trend, opportunity
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    product_area: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Evidence
    evidence_sources: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)

    # Analytical lenses applied
    academic_perspective: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_perspective: Mapped[str | None] = mapped_column(Text, nullable=True)
    ux_perspective: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Status
    status: Mapped[str] = mapped_column(
        String(20), default="active"
    )  # active, acted_upon, dismissed, archived
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PriorityScore(Base, TenantMixin, TimestampMixin):
    """Continuously updated priority scores for product development decisions."""

    __tablename__ = "priority_scores"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    product_area: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)  # 0-100
    rank: Mapped[int] = mapped_column(Integer, nullable=False)

    # Component scores
    friction_score: Mapped[float] = mapped_column(Float, default=0.0)
    voc_score: Mapped[float] = mapped_column(Float, default=0.0)
    competitive_score: Mapped[float] = mapped_column(Float, default=0.0)
    telemetry_score: Mapped[float] = mapped_column(Float, default=0.0)
    strategic_score: Mapped[float] = mapped_column(Float, default=0.0)

    # Context
    top_signals: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ExperimentRecommendation(Base, TenantMixin, TimestampMixin):
    """Ranked experiment hypotheses generated from analysis."""

    __tablename__ = "experiment_recommendations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    product_area: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expected_impact: Mapped[str] = mapped_column(Text, nullable=False)
    expected_revenue_impact: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    effort_estimate: Mapped[str] = mapped_column(
        String(20), default="medium"
    )  # low, medium, high
    variants: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    evidence_sources: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    status: Mapped[str] = mapped_column(
        String(20), default="proposed"
    )  # proposed, approved, running, completed, rejected
    rank: Mapped[int] = mapped_column(Integer, default=0)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RecommendationOutcome(Base, TenantMixin, TimestampMixin):
    """Self-improvement loop: tracks whether recommendations moved metrics."""

    __tablename__ = "recommendation_outcomes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    recommendation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    recommendation_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # experiment, friction_fix, competitive_response
    target_metric: Mapped[str] = mapped_column(String(255), nullable=False)
    baseline_value: Mapped[float] = mapped_column(Float, nullable=False)
    outcome_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # positive, neutral, negative
    revenue_impact: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    measured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
