"""Competitive deep-dive analysis engine — on-demand comprehensive competitor analysis."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from observatory.core.llm import get_llm_service
from observatory.core.models.competitor import (
    CompetitorChange,
    CompetitorProfile,
    CompetitorReview,
    SocialMention,
)

logger = structlog.get_logger()


class CompetitiveDeepDive:
    """Generates comprehensive deep-dive analysis for a specific competitor."""

    def __init__(self, db: AsyncSession, org_id: uuid.UUID):
        self.db = db
        self.org_id = org_id
        self.llm = get_llm_service()

    async def generate(
        self,
        competitor_id: uuid.UUID,
        lookback_days: int = 90,
    ) -> dict[str, Any]:
        """Generate a full deep-dive report for a competitor."""
        competitor = await self._get_competitor(competitor_id)
        if not competitor:
            raise ValueError(f"Competitor {competitor_id} not found")

        since = datetime.now(timezone.utc) - timedelta(days=lookback_days)

        # Gather all intelligence
        changes = await self._get_changes(competitor_id, since)
        reviews = await self._get_reviews(competitor_id, since)
        mentions = await self._get_social_mentions(competitor.name, since)

        # Build evidence corpus
        evidence = self._build_evidence_corpus(competitor, changes, reviews, mentions)

        # Generate analysis sections
        strategy_analysis = await self._analyze_strategy(competitor, evidence)
        product_analysis = await self._analyze_product_moves(competitor, changes)
        sentiment_analysis = await self._analyze_sentiment(competitor, reviews, mentions)
        threat_assessment = await self._assess_threat(competitor, evidence)

        report = {
            "competitor_id": str(competitor_id),
            "competitor_name": competitor.name,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "lookback_days": lookback_days,
            "data_summary": {
                "changes_analyzed": len(changes),
                "reviews_analyzed": len(reviews),
                "mentions_analyzed": len(mentions),
            },
            "strategy": strategy_analysis,
            "product_moves": product_analysis,
            "sentiment": sentiment_analysis,
            "threat_assessment": threat_assessment,
            "raw_evidence": evidence[:50],  # Cap for payload size
        }

        logger.info(
            "competitive_deep_dive_complete",
            org_id=str(self.org_id),
            competitor=competitor.name,
            evidence_pieces=len(evidence),
        )
        return report

    async def _get_competitor(self, competitor_id: uuid.UUID) -> CompetitorProfile | None:
        result = await self.db.execute(
            select(CompetitorProfile).where(
                CompetitorProfile.id == competitor_id,
                CompetitorProfile.org_id == self.org_id,
            )
        )
        return result.scalar_one_or_none()

    async def _get_changes(self, competitor_id: uuid.UUID, since: datetime) -> list:
        result = await self.db.execute(
            select(CompetitorChange)
            .where(
                CompetitorChange.competitor_id == competitor_id,
                CompetitorChange.detected_at >= since,
            )
            .order_by(CompetitorChange.detected_at.desc())
            .limit(200)
        )
        return result.scalars().all()

    async def _get_reviews(self, competitor_id: uuid.UUID, since: datetime) -> list:
        result = await self.db.execute(
            select(CompetitorReview)
            .where(
                CompetitorReview.competitor_id == competitor_id,
                CompetitorReview.created_at >= since,
            )
            .order_by(CompetitorReview.created_at.desc())
            .limit(200)
        )
        return result.scalars().all()

    async def _get_social_mentions(self, competitor_name: str, since: datetime) -> list:
        result = await self.db.execute(
            select(SocialMention)
            .where(
                SocialMention.org_id == self.org_id,
                SocialMention.mentions_competitor == competitor_name,
                SocialMention.posted_at >= since,
            )
            .order_by(SocialMention.posted_at.desc())
            .limit(200)
        )
        return result.scalars().all()

    def _build_evidence_corpus(
        self,
        competitor: CompetitorProfile,
        changes: list,
        reviews: list,
        mentions: list,
    ) -> list[dict]:
        evidence = []

        for c in changes:
            evidence.append({
                "type": "change",
                "title": c.title,
                "content": c.description or "",
                "significance": c.significance,
                "change_type": c.change_type,
                "date": c.detected_at.isoformat() if c.detected_at else None,
                "source_url": c.source_url,
            })

        for r in reviews:
            evidence.append({
                "type": "review",
                "title": r.title or "",
                "content": r.text or "",
                "rating": r.rating,
                "platform": r.platform,
                "date": r.created_at.isoformat() if r.created_at else None,
            })

        for m in mentions:
            evidence.append({
                "type": "social_mention",
                "title": "",
                "content": m.text or "",
                "platform": m.platform,
                "engagement": m.engagement_score,
                "date": m.posted_at.isoformat() if m.posted_at else None,
                "source_url": m.source_url,
            })

        return evidence

    async def _analyze_strategy(
        self, competitor: CompetitorProfile, evidence: list[dict]
    ) -> dict[str, Any]:
        evidence_summary = self._summarize_evidence(evidence, max_items=30)

        prompt = (
            f"Analyze the competitive strategy of {competitor.name} based on this evidence:\n\n"
            f"{evidence_summary}\n\n"
            "Provide analysis in this format:\n"
            "POSITIONING: How they position themselves in the market (1-2 sentences)\n"
            "STRATEGY_TYPE: Their apparent strategy (cost leader / differentiator / niche / disruptor)\n"
            "KEY_MOVES: Top 3-5 strategic moves observed\n"
            "TRAJECTORY: Where they appear to be heading\n"
            "BEHAVIORAL_PATTERNS: Recurring patterns in their actions (release cadence, messaging themes, pricing moves)"
        )

        try:
            analysis = await self.llm.complete(prompt=prompt, tier="SYNTHESIS")
            return {"analysis": analysis, "evidence_count": len(evidence)}
        except Exception as e:
            logger.error("strategy_analysis_error", error=str(e))
            return {"analysis": "Analysis unavailable", "evidence_count": len(evidence)}

    async def _analyze_product_moves(
        self, competitor: CompetitorProfile, changes: list
    ) -> dict[str, Any]:
        if not changes:
            return {"analysis": "No product changes detected in the analysis period.", "changes": []}

        change_list = "\n".join(
            f"- [{c.change_type}] {c.title} (significance: {c.significance})"
            for c in changes[:30]
        )

        prompt = (
            f"Analyze {competitor.name}'s product changes:\n\n{change_list}\n\n"
            "Provide:\n"
            "PRODUCT_DIRECTION: What product direction do these changes indicate?\n"
            "FEATURE_GAPS: What feature gaps might they be trying to close?\n"
            "INVESTMENT_AREAS: Where are they investing most heavily?\n"
            "IMPLICATIONS_FOR_US: What should we consider in response?"
        )

        try:
            analysis = await self.llm.complete(prompt=prompt, tier="SYNTHESIS")
        except Exception as e:
            logger.error("product_analysis_error", error=str(e))
            analysis = "Analysis unavailable"

        return {
            "analysis": analysis,
            "changes": [
                {
                    "title": c.title,
                    "type": c.change_type,
                    "significance": c.significance,
                }
                for c in changes[:20]
            ],
        }

    async def _analyze_sentiment(
        self, competitor: CompetitorProfile, reviews: list, mentions: list
    ) -> dict[str, Any]:
        review_text = "\n".join(
            f"- [Rating: {r.rating}/5] {(r.text or '')[:200]}"
            for r in reviews[:20]
        )
        mention_text = "\n".join(
            f"- [{m.platform}] {(m.text or '')[:200]}"
            for m in mentions[:20]
        )

        if not review_text and not mention_text:
            return {
                "analysis": "Insufficient data for sentiment analysis.",
                "avg_rating": None,
                "review_count": 0,
                "mention_count": 0,
            }

        prompt = (
            f"Analyze public sentiment about {competitor.name}:\n\n"
            f"REVIEWS:\n{review_text or 'No reviews available'}\n\n"
            f"SOCIAL MENTIONS:\n{mention_text or 'No mentions available'}\n\n"
            "Provide:\n"
            "OVERALL_SENTIMENT: Positive / Mixed / Negative with reasoning\n"
            "STRENGTHS_PRAISED: What users love about them\n"
            "COMMON_COMPLAINTS: Recurring pain points\n"
            "VULNERABILITY: Their biggest vulnerability we could exploit\n"
            "SENTIMENT_TREND: Is sentiment improving or declining?"
        )

        try:
            analysis = await self.llm.complete(prompt=prompt, tier="SYNTHESIS")
        except Exception as e:
            logger.error("sentiment_analysis_error", error=str(e))
            analysis = "Analysis unavailable"

        avg_rating = None
        rated_reviews = [r for r in reviews if r.rating is not None]
        if rated_reviews:
            avg_rating = round(sum(r.rating for r in rated_reviews) / len(rated_reviews), 2)

        return {
            "analysis": analysis,
            "avg_rating": avg_rating,
            "review_count": len(reviews),
            "mention_count": len(mentions),
        }

    async def _assess_threat(
        self, competitor: CompetitorProfile, evidence: list[dict]
    ) -> dict[str, Any]:
        evidence_summary = self._summarize_evidence(evidence, max_items=20)

        prompt = (
            f"Based on the following intelligence about {competitor.name}, assess the competitive threat:\n\n"
            f"{evidence_summary}\n\n"
            "Provide:\n"
            "THREAT_LEVEL: Low / Medium / High / Critical — with reasoning\n"
            "AREAS_OF_OVERLAP: Where do they compete directly with us?\n"
            "DIFFERENTIATION_RISK: Where are they differentiating in ways that threaten us?\n"
            "TIMELINE: How urgent is this threat? (immediate / 3-6 months / 6-12 months / long-term)\n"
            "RECOMMENDED_RESPONSE: Top 3 actions to take"
        )

        try:
            analysis = await self.llm.complete(prompt=prompt, tier="SYNTHESIS")
            return {"analysis": analysis}
        except Exception as e:
            logger.error("threat_assessment_error", error=str(e))
            return {"analysis": "Assessment unavailable"}

    def _summarize_evidence(self, evidence: list[dict], max_items: int = 30) -> str:
        lines = []
        for e in evidence[:max_items]:
            etype = e.get("type", "unknown")
            content = e.get("content", "")[:200]
            title = e.get("title", "")
            if title:
                lines.append(f"[{etype}] {title}: {content}")
            else:
                lines.append(f"[{etype}] {content}")
        return "\n".join(lines)
