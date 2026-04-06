"""Battlecard generator — auto-generates competitive battlecards from accumulated intelligence."""

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from observatory.core.llm.service import LLMService
from observatory.core.models.competitor import (
    CompetitorChange,
    CompetitorProfile,
    CompetitorReview,
    SocialMention,
)

logger = structlog.get_logger()

BATTLECARD_SYSTEM = """You are Observatory's battlecard generator. Produce a structured competitive battlecard for sales and marketing teams.

Output JSON matching this schema:
{
    "competitor_name": "...",
    "last_updated": "ISO date",
    "overview": "2-3 sentence competitor summary",
    "strengths": ["list of their key strengths"],
    "weaknesses": ["list of their key weaknesses"],
    "our_differentiators": ["how we are better"],
    "their_differentiators": ["how they are better"],
    "recent_changes": ["notable recent moves"],
    "common_objections": [
        {"objection": "...", "response": "..."}
    ],
    "win_themes": ["key themes for winning against this competitor"],
    "loss_reasons": ["common reasons deals are lost to this competitor"],
    "pricing_comparison": "what we know about their pricing vs ours"
}

Be factual. Only include information supported by the evidence provided. Mark uncertainty clearly."""


class BattlecardGenerator:
    def __init__(self, llm: LLMService, db: AsyncSession):
        self.llm = llm
        self.db = db

    async def generate_battlecard(
        self, org_id: uuid.UUID, competitor_id: uuid.UUID
    ) -> dict:
        """Generate a comprehensive battlecard for a competitor."""
        # Fetch competitor profile
        comp_result = await self.db.execute(
            select(CompetitorProfile).where(
                CompetitorProfile.id == competitor_id,
                CompetitorProfile.org_id == org_id,
            )
        )
        competitor = comp_result.scalar_one_or_none()
        if not competitor:
            raise ValueError(f"Competitor {competitor_id} not found")

        context = [f"COMPETITOR: {competitor.name}\nDescription: {competitor.description or 'N/A'}"]

        # Recent changes
        changes_result = await self.db.execute(
            select(CompetitorChange)
            .where(
                CompetitorChange.org_id == org_id,
                CompetitorChange.competitor_id == competitor_id,
            )
            .order_by(desc(CompetitorChange.detected_at))
            .limit(20)
        )
        changes = changes_result.scalars().all()
        if changes:
            changes_text = "\n".join(
                f"- [{c.detected_at.date()}] [{c.change_type}] {c.title}: {c.description[:300]}"
                for c in changes
            )
            context.append(f"RECENT CHANGES:\n{changes_text}")

        # Reviews
        reviews_result = await self.db.execute(
            select(CompetitorReview)
            .where(
                CompetitorReview.org_id == org_id,
                CompetitorReview.competitor_id == competitor_id,
            )
            .order_by(desc(CompetitorReview.posted_at))
            .limit(30)
        )
        reviews = reviews_result.scalars().all()
        if reviews:
            reviews_text = "\n".join(
                f"- [{r.platform}] {r.rating}/5: {r.text[:200]}"
                for r in reviews
            )
            context.append(f"CUSTOMER REVIEWS:\n{reviews_text}")

        # Social mentions
        mentions_result = await self.db.execute(
            select(SocialMention)
            .where(
                SocialMention.org_id == org_id,
                SocialMention.mentions_competitor == competitor.name,
            )
            .order_by(desc(SocialMention.posted_at))
            .limit(20)
        )
        mentions = mentions_result.scalars().all()
        if mentions:
            mentions_text = "\n".join(
                f"- [{m.platform}] {m.sentiment}: {m.text[:200]}"
                for m in mentions
            )
            context.append(f"SOCIAL MENTIONS:\n{mentions_text}")

        import json

        result = await self.llm.synthesize(
            context=context,
            prompt=f"Generate a battlecard for {competitor.name}.",
            system=BATTLECARD_SYSTEM,
        )

        try:
            battlecard = json.loads(result)
        except json.JSONDecodeError:
            logger.error("battlecard_parse_error", competitor=competitor.name)
            battlecard = {"competitor_name": competitor.name, "error": "Failed to parse"}

        logger.info(
            "battlecard_generated",
            org_id=str(org_id),
            competitor=competitor.name,
        )
        return battlecard
