import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from observatory.core.models.base import Base, TenantMixin, TimestampMixin


class ResearchBrief(Base, TenantMixin, TimestampMixin):
    """Auto-generated research briefs for knowledge gaps."""

    __tablename__ = "research_briefs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    knowledge_gap: Mapped[str] = mapped_column(Text, nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    methodology: Mapped[str] = mapped_column(Text, nullable=False)
    sample_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sample_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_cost_currency: Mapped[str] = mapped_column(String(3), default="GBP")
    expected_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_value_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    product_area: Mapped[str | None] = mapped_column(String(255), nullable=True)
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    status: Mapped[str] = mapped_column(
        String(20), default="draft"
    )  # draft, pending_review, approved, commissioned, completed, rejected
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_sources: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class ResearchCommission(Base, TenantMixin, TimestampMixin):
    """Tracking commissioned research through external providers."""

    __tablename__ = "research_commissions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    brief_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)  # askable, usertesting, etc.
    provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actual_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending, in_progress, completed, cancelled
    commissioned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    findings_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )  # links to KnowledgeDocument
