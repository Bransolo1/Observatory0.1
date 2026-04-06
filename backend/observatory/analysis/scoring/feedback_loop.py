"""Self-improvement feedback loop — tracks outcomes and adjusts scoring weights."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from observatory.core.models.insight import (
    ExperimentRecommendation,
    RecommendationOutcome,
)

logger = structlog.get_logger()

# Default weights — can be adjusted based on outcome data
DEFAULT_WEIGHTS = {
    "friction": 0.30,
    "voc": 0.25,
    "competitive": 0.15,
    "telemetry": 0.20,
    "strategic": 0.10,
}


class FeedbackLoop:
    """Tracks recommendation outcomes and adjusts scoring weights."""

    def __init__(self, db: AsyncSession, org_id: uuid.UUID):
        self.db = db
        self.org_id = org_id

    async def record_outcome(
        self,
        recommendation_id: uuid.UUID,
        recommendation_type: str,
        target_metric: str,
        baseline_value: float | None = None,
        outcome_value: float | None = None,
        outcome: str | None = None,
        revenue_impact: float | None = None,
        notes: str | None = None,
    ) -> RecommendationOutcome:
        """Record the outcome of an acted-upon recommendation."""
        # Auto-determine outcome if values provided
        if outcome is None and baseline_value is not None and outcome_value is not None:
            if outcome_value > baseline_value * 1.05:
                outcome = "positive"
            elif outcome_value < baseline_value * 0.95:
                outcome = "negative"
            else:
                outcome = "neutral"

        record = RecommendationOutcome(
            org_id=self.org_id,
            recommendation_id=recommendation_id,
            recommendation_type=recommendation_type,
            target_metric=target_metric,
            baseline_value=baseline_value,
            outcome_value=outcome_value,
            outcome=outcome,
            revenue_impact=revenue_impact,
            notes=notes,
            measured_at=datetime.now(timezone.utc),
        )

        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)

        logger.info(
            "outcome_recorded",
            org_id=str(self.org_id),
            recommendation_id=str(recommendation_id),
            outcome=outcome,
            revenue_impact=revenue_impact,
        )
        return record

    async def get_outcome_stats(self, lookback_days: int = 90) -> dict[str, Any]:
        """Get aggregate outcome statistics for the organization."""
        since = datetime.now(timezone.utc) - timedelta(days=lookback_days)

        # Total outcomes
        total_result = await self.db.execute(
            select(func.count(RecommendationOutcome.id)).where(
                RecommendationOutcome.org_id == self.org_id,
                RecommendationOutcome.measured_at >= since,
            )
        )
        total = total_result.scalar() or 0

        # Outcomes by result
        outcome_result = await self.db.execute(
            select(
                RecommendationOutcome.outcome,
                func.count(RecommendationOutcome.id),
            )
            .where(
                RecommendationOutcome.org_id == self.org_id,
                RecommendationOutcome.measured_at >= since,
            )
            .group_by(RecommendationOutcome.outcome)
        )
        by_outcome = {row[0]: row[1] for row in outcome_result.all() if row[0]}

        # Outcomes by type
        type_result = await self.db.execute(
            select(
                RecommendationOutcome.recommendation_type,
                RecommendationOutcome.outcome,
                func.count(RecommendationOutcome.id),
            )
            .where(
                RecommendationOutcome.org_id == self.org_id,
                RecommendationOutcome.measured_at >= since,
            )
            .group_by(
                RecommendationOutcome.recommendation_type,
                RecommendationOutcome.outcome,
            )
        )
        by_type: dict[str, dict[str, int]] = {}
        for row in type_result.all():
            rtype = row[0] or "unknown"
            outcome_val = row[1] or "unknown"
            if rtype not in by_type:
                by_type[rtype] = {}
            by_type[rtype][outcome_val] = row[2]

        # Total revenue impact
        revenue_result = await self.db.execute(
            select(func.sum(RecommendationOutcome.revenue_impact)).where(
                RecommendationOutcome.org_id == self.org_id,
                RecommendationOutcome.measured_at >= since,
            )
        )
        total_revenue_impact = revenue_result.scalar() or 0.0

        # Hit rate (positive outcomes / total)
        positive_count = by_outcome.get("positive", 0)
        hit_rate = (positive_count / total * 100) if total > 0 else 0.0

        return {
            "period_days": lookback_days,
            "total_outcomes": total,
            "by_outcome": by_outcome,
            "by_type": by_type,
            "hit_rate": round(hit_rate, 1),
            "total_revenue_impact": round(float(total_revenue_impact), 2),
        }

    async def calculate_adjusted_weights(self) -> dict[str, float]:
        """Calculate adjusted scoring weights based on outcome data.

        If friction-sourced recommendations have high hit rates, increase friction weight.
        If competitive-sourced recs have low hit rates, decrease competitive weight.
        """
        stats = await self.get_outcome_stats(lookback_days=180)
        by_type = stats.get("by_type", {})

        if stats["total_outcomes"] < 10:
            # Not enough data to adjust — use defaults
            return dict(DEFAULT_WEIGHTS)

        # Calculate hit rate per recommendation type
        type_hit_rates: dict[str, float] = {}
        for rtype, outcomes in by_type.items():
            total_for_type = sum(outcomes.values())
            positive_for_type = outcomes.get("positive", 0)
            if total_for_type > 0:
                type_hit_rates[rtype] = positive_for_type / total_for_type

        # Map recommendation types to weight components
        type_to_weight = {
            "friction_fix": "friction",
            "experiment": "voc",  # experiments often driven by VoC
            "competitive_response": "competitive",
        }

        # Adjust weights based on hit rates
        adjusted = dict(DEFAULT_WEIGHTS)
        for rtype, hit_rate in type_hit_rates.items():
            weight_key = type_to_weight.get(rtype)
            if weight_key and weight_key in adjusted:
                # Nudge weight up/down by up to 5% based on hit rate vs 50% baseline
                adjustment = (hit_rate - 0.5) * 0.10  # ±5% max
                adjusted[weight_key] = max(0.05, min(0.50, adjusted[weight_key] + adjustment))

        # Normalize to sum to 1.0
        total = sum(adjusted.values())
        if total > 0:
            adjusted = {k: round(v / total, 4) for k, v in adjusted.items()}

        logger.info(
            "weights_adjusted",
            org_id=str(self.org_id),
            original=DEFAULT_WEIGHTS,
            adjusted=adjusted,
            type_hit_rates=type_hit_rates,
        )
        return adjusted
