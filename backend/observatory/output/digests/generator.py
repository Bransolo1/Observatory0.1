"""Digest generator — produces weekly competitive intelligence and monthly CEO digests."""

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from observatory.core.llm.service import LLMService
from observatory.core.models.competitor import CompetitorChange, CompetitorProfile
from observatory.core.models.insight import (
    ExperimentRecommendation,
    Insight,
    PriorityScore,
)
from observatory.core.models.telemetry import FrictionSignal

logger = structlog.get_logger()

WEEKLY_DIGEST_SYSTEM = """You are Observatory's digest generator. Produce a concise, actionable weekly intelligence digest for product and marketing teams.

Structure:
1. **TL;DR** — 3 bullet points max, biggest things to know this week
2. **Competitive Movements** — what competitors did this week
3. **Friction Alerts** — new or worsened user friction points
4. **Top Experiments to Run** — the highest-impact experiments this week
5. **Priority Shifts** — what moved up or down in priority and why

Be specific. Use data. Keep it under 800 words. Write for a busy Head of Product who has 5 minutes."""

CEO_DIGEST_SYSTEM = """You are Observatory's executive digest generator. Produce a strategic monthly overview for a CEO/MD.

Structure:
1. **Executive Summary** — 3-4 sentences on the most important developments
2. **Biggest Competitive Threat** — the single most significant competitive movement
3. **Top Opportunity** — the highest-impact opportunity identified this month
4. **Key Metrics** — insights acted upon, experiments run, win rate
5. **Recommended Actions** — 2-3 strategic decisions to consider

Write for a CEO who wants signal, not noise. Under 500 words."""


class DigestGenerator:
    def __init__(self, llm: LLMService, db: AsyncSession):
        self.llm = llm
        self.db = db

    async def generate_weekly_digest(self, org_id: uuid.UUID) -> str:
        """Generate the weekly competitive intelligence digest."""
        lookback = datetime.now(timezone.utc) - timedelta(days=7)

        # Gather this week's data
        context = []

        # Competitor changes
        changes_result = await self.db.execute(
            select(CompetitorChange)
            .where(CompetitorChange.org_id == org_id, CompetitorChange.detected_at >= lookback)
            .order_by(desc(CompetitorChange.detected_at))
        )
        changes = changes_result.scalars().all()
        if changes:
            changes_text = "\n".join(
                f"- [{c.significance}] {c.change_type}: {c.title} — {c.description[:200]}"
                for c in changes
            )
            context.append(f"COMPETITOR CHANGES THIS WEEK:\n{changes_text}")

        # New friction signals
        friction_result = await self.db.execute(
            select(FrictionSignal)
            .where(FrictionSignal.org_id == org_id, FrictionSignal.detected_at >= lookback)
            .order_by(desc(FrictionSignal.deviation_score))
        )
        frictions = friction_result.scalars().all()
        if frictions:
            friction_text = "\n".join(
                f"- [{f.severity}] {f.product_area}: {f.description or f.funnel_step}"
                for f in frictions
            )
            context.append(f"NEW FRICTION SIGNALS:\n{friction_text}")

        # Top experiments
        exp_result = await self.db.execute(
            select(ExperimentRecommendation)
            .where(
                ExperimentRecommendation.org_id == org_id,
                ExperimentRecommendation.status == "proposed",
            )
            .order_by(ExperimentRecommendation.rank)
            .limit(3)
        )
        experiments = exp_result.scalars().all()
        if experiments:
            exp_text = "\n".join(
                f"- #{e.rank}: {e.title} (confidence: {e.confidence:.0%}, effort: {e.effort_estimate})"
                for e in experiments
            )
            context.append(f"TOP EXPERIMENT RECOMMENDATIONS:\n{exp_text}")

        # Priority scores
        scores_result = await self.db.execute(
            select(PriorityScore)
            .where(PriorityScore.org_id == org_id)
            .order_by(PriorityScore.rank)
            .limit(5)
        )
        scores = scores_result.scalars().all()
        if scores:
            scores_text = "\n".join(
                f"- #{s.rank} {s.product_area}: {s.score:.0f}"
                for s in scores
            )
            context.append(f"CURRENT PRIORITY RANKINGS:\n{scores_text}")

        if not context:
            return "No significant intelligence to report this week."

        digest = await self.llm.synthesize(
            context=context,
            prompt="Generate the weekly intelligence digest.",
            system=WEEKLY_DIGEST_SYSTEM,
        )

        logger.info("weekly_digest_generated", org_id=str(org_id))
        return digest

    async def generate_ceo_digest(self, org_id: uuid.UUID) -> str:
        """Generate the monthly CEO/MD strategic digest."""
        lookback = datetime.now(timezone.utc) - timedelta(days=30)

        context = []

        # Key insights this month
        insights_result = await self.db.execute(
            select(Insight)
            .where(Insight.org_id == org_id, Insight.generated_at >= lookback)
            .order_by(desc(Insight.confidence))
            .limit(10)
        )
        insights = insights_result.scalars().all()
        if insights:
            insights_text = "\n".join(
                f"- [{i.insight_type}] {i.title}: {i.summary[:200]}"
                for i in insights
            )
            context.append(f"KEY INSIGHTS THIS MONTH:\n{insights_text}")

        # Priority scores
        scores_result = await self.db.execute(
            select(PriorityScore)
            .where(PriorityScore.org_id == org_id)
            .order_by(PriorityScore.rank)
            .limit(5)
        )
        scores = scores_result.scalars().all()
        if scores:
            scores_text = "\n".join(
                f"- #{s.rank} {s.product_area}: {s.score:.0f}"
                for s in scores
            )
            context.append(f"CURRENT PRIORITIES:\n{scores_text}")

        if not context:
            return "Insufficient data for monthly executive digest."

        digest = await self.llm.synthesize(
            context=context,
            prompt="Generate the monthly CEO digest.",
            system=CEO_DIGEST_SYSTEM,
        )

        logger.info("ceo_digest_generated", org_id=str(org_id))
        return digest
