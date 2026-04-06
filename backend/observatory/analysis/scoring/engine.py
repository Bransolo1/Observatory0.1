"""Priority scoring engine — generates ranked scores for product development decisions."""

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from observatory.core.llm.service import LLMService
from observatory.core.models.competitor import CompetitorChange
from observatory.core.models.feedback import Feedback
from observatory.core.models.insight import PriorityScore
from observatory.core.models.telemetry import FrictionSignal

logger = structlog.get_logger()

# Default weights for the priority scoring components
DEFAULT_WEIGHTS = {
    "friction": 0.30,
    "voc": 0.25,
    "competitive": 0.15,
    "telemetry": 0.20,
    "strategic": 0.10,
}


class PriorityScoringEngine:
    def __init__(self, llm: LLMService, db: AsyncSession, weights: dict | None = None):
        self.llm = llm
        self.db = db
        self.weights = weights or DEFAULT_WEIGHTS

    async def score_product_area(self, org_id: uuid.UUID, product_area: str) -> PriorityScore:
        """Calculate a priority score for a single product area."""
        lookback = datetime.now(timezone.utc) - timedelta(days=30)

        # Friction score: based on active friction signals
        friction_result = await self.db.execute(
            select(func.count(), func.avg(FrictionSignal.deviation_score)).where(
                FrictionSignal.org_id == org_id,
                FrictionSignal.product_area == product_area,
                FrictionSignal.status == "active",
                FrictionSignal.detected_at >= lookback,
            )
        )
        friction_row = friction_result.one()
        friction_count = friction_row[0] or 0
        friction_avg_deviation = friction_row[1] or 0
        friction_score = min(100, friction_count * 20 + friction_avg_deviation * 10)

        # VoC score: based on negative feedback volume and urgency
        voc_result = await self.db.execute(
            select(func.count()).where(
                Feedback.org_id == org_id,
                Feedback.product_areas.contains([product_area]),
                Feedback.sentiment.in_(["negative", "mixed"]),
                Feedback.source_created_at >= lookback,
            )
        )
        negative_feedback_count = voc_result.scalar() or 0
        voc_score = min(100, negative_feedback_count * 5)

        # Competitive score: based on recent competitor changes in this area
        comp_result = await self.db.execute(
            select(func.count()).where(
                CompetitorChange.org_id == org_id,
                CompetitorChange.detected_at >= lookback,
            )
        )
        comp_changes = comp_result.scalar() or 0
        competitive_score = min(100, comp_changes * 15)

        # Telemetry score: based on volume of affected users from friction signals
        telem_result = await self.db.execute(
            select(func.sum(FrictionSignal.affected_users)).where(
                FrictionSignal.org_id == org_id,
                FrictionSignal.product_area == product_area,
                FrictionSignal.status == "active",
            )
        )
        affected_users = telem_result.scalar() or 0
        telemetry_score = min(100, affected_users / 10)

        # Strategic score: placeholder — in future driven by org strategy config
        strategic_score = 50.0

        # Weighted composite
        composite = (
            friction_score * self.weights["friction"]
            + voc_score * self.weights["voc"]
            + competitive_score * self.weights["competitive"]
            + telemetry_score * self.weights["telemetry"]
            + strategic_score * self.weights["strategic"]
        )

        return PriorityScore(
            org_id=org_id,
            product_area=product_area,
            score=round(composite, 2),
            rank=0,  # set after all areas scored
            friction_score=round(friction_score, 2),
            voc_score=round(voc_score, 2),
            competitive_score=round(competitive_score, 2),
            telemetry_score=round(telemetry_score, 2),
            strategic_score=round(strategic_score, 2),
            scored_at=datetime.now(timezone.utc),
        )

    async def recalculate_all(self, org_id: uuid.UUID) -> list[PriorityScore]:
        """Recalculate scores for all product areas in an org."""
        # Get all known product areas from feedback and friction signals
        areas_result = await self.db.execute(
            select(FrictionSignal.product_area)
            .where(FrictionSignal.org_id == org_id)
            .distinct()
        )
        areas = {row[0] for row in areas_result.all() if row[0]}

        feedback_areas_result = await self.db.execute(
            select(func.unnest(Feedback.product_areas))
            .where(Feedback.org_id == org_id)
            .distinct()
        )
        areas.update({row[0] for row in feedback_areas_result.all() if row[0]})

        scores = []
        for area in areas:
            score = await self.score_product_area(org_id, area)
            scores.append(score)

        # Assign ranks
        scores.sort(key=lambda s: s.score, reverse=True)
        for rank, score in enumerate(scores, 1):
            score.rank = rank
            self.db.add(score)

        await self.db.commit()

        logger.info(
            "priority_scores_recalculated",
            org_id=str(org_id),
            areas_scored=len(scores),
        )
        return scores
