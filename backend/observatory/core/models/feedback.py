import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from observatory.core.models.base import Base, TenantMixin, TimestampMixin


class ProductArea(Base, TenantMixin, TimestampMixin):
    __tablename__ = "product_areas"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_areas.id"), nullable=True
    )


class FeedbackCategory(Base, TenantMixin, TimestampMixin):
    __tablename__ = "feedback_categories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)


class Feedback(Base, TenantMixin, TimestampMixin):
    """Normalized feedback from all VoC sources (Zendesk, app stores, Intercom, etc.)."""

    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # zendesk, app_store_ios, app_store_android, intercom, etc.
    source_id: Mapped[str] = mapped_column(
        String(255), nullable=False
    )  # external ID from source system
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Content
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-5 for app reviews

    # LLM-enriched fields
    sentiment: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # positive, negative, neutral, mixed
    sentiment_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # -1.0 to 1.0
    urgency: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # low, medium, high, critical
    product_areas: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    themes: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Metadata
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, server_default="{}")
    source_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Vector embedding for semantic search
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
