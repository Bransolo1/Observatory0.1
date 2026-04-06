import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from observatory.core.models.base import Base, TenantMixin, TimestampMixin


class CompetitorProfile(Base, TenantMixin, TimestampMixin):
    __tablename__ = "competitor_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    website_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tracking_config: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )  # URLs to monitor, social handles, etc.
    is_active: Mapped[bool] = mapped_column(default=True)


class CompetitorChange(Base, TenantMixin, TimestampMixin):
    """Detected changes in competitor behaviour (pricing, features, UX, messaging)."""

    __tablename__ = "competitor_changes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    competitor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    change_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # pricing, feature, ux, messaging, promotion
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    significance: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # low, medium, high, critical
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SocialMention(Base, TenantMixin, TimestampMixin):
    __tablename__ = "social_mentions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    platform: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # reddit, twitter, hackernews
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sentiment_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    topics: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    mentions_competitor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    engagement_score: Mapped[int] = mapped_column(Integer, default=0)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)


class CompetitorReview(Base, TenantMixin, TimestampMixin):
    __tablename__ = "competitor_reviews"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    competitor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # g2, capterra, trustpilot, app_store
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    themes: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
