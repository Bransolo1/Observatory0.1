"""Experiment recommendation engine — generates ranked hypotheses from friction + competitive data."""

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from observatory.core.llm.service import LLMService
from observatory.core.models.insight import ExperimentRecommendation, Insight, PriorityScore
from observatory.core.models.telemetry import FrictionSignal

logger = structlog.get_logger()

EXPERIMENT_SYSTEM_PROMPT = """You are Observatory's experiment recommendation engine. Your job is to transform friction points and competitive gaps into testable A/B experiment hypotheses.

For each experiment, produce:
1. A clear, testable hypothesis statement
2. Specific control and variant descriptions
3. Expected impact (qualitative and quantitative estimate)
4. Confidence level based on evidence strength
5. Effort estimate (low/medium/high)

Ground every recommendation in specific evidence from the data provided. Do not speculate beyond what the evidence supports.

Respond with valid JSON array of experiments:
[{
    "title": "...",
    "hypothesis": "If we [change], then [metric] will [improve/decrease] by [estimate] because [reason from evidence]",
    "expected_impact": "...",
    "expected_revenue_impact": float or null,
    "confidence": float 0-1,
    "effort_estimate": "low|medium|high",
    "variants": {"control": "...", "treatment": "..."},
    "evidence": ["list of evidence points"]
}]"""


class ExperimentRecommender:
    def __init__(self, llm: LLMService, db: AsyncSession):
        self.llm = llm
        self.db = db

    async def generate_recommendations(
        self, org_id: uuid.UUID, top_n: int = 3
    ) -> list[ExperimentRecommendation]:
        """Generate top-N experiment recommendations based on current intelligence."""
        # Gather top friction points
        friction_result = await self.db.execute(
            select(FrictionSignal)
            .where(FrictionSignal.org_id == org_id, FrictionSignal.status == "active")
            .order_by(FrictionSignal.deviation_score.desc())
            .limit(5)
        )
        friction_signals = friction_result.scalars().all()

        # Gather top insights
        insights_result = await self.db.execute(
            select(Insight)
            .where(Insight.org_id == org_id, Insight.status == "active")
            .order_by(Insight.confidence.desc())
            .limit(5)
        )
        insights = insights_result.scalars().all()

        # Gather priority scores for context
        scores_result = await self.db.execute(
            select(PriorityScore)
            .where(PriorityScore.org_id == org_id)
            .order_by(PriorityScore.rank)
            .limit(10)
        )
        priority_scores = scores_result.scalars().all()

        # Build context for LLM
        context = []

        if friction_signals:
            friction_text = "\n".join(
                f"- [{f.severity}] {f.product_area}: {f.description or f.funnel_step} "
                f"(deviation: {f.deviation_score:.1f}σ, affected: {f.affected_users} users)"
                for f in friction_signals
            )
            context.append(f"ACTIVE FRICTION POINTS:\n{friction_text}")

        if insights:
            insights_text = "\n".join(
                f"- [{i.insight_type}] {i.title}: {i.summary}"
                for i in insights
            )
            context.append(f"ACTIVE INSIGHTS:\n{insights_text}")

        if priority_scores:
            scores_text = "\n".join(
                f"- #{s.rank} {s.product_area}: score {s.score:.0f} "
                f"(friction={s.friction_score:.0f}, voc={s.voc_score:.0f})"
                for s in priority_scores
            )
            context.append(f"PRIORITY SCORES:\n{scores_text}")

        if not context:
            return []

        import json

        result = await self.llm.synthesize(
            context=context,
            prompt=f"Generate the top {top_n} experiment recommendations based on this data.",
            system=EXPERIMENT_SYSTEM_PROMPT,
        )

        try:
            experiments_data = json.loads(result)
        except json.JSONDecodeError:
            logger.error("experiment_json_parse_error", raw=result[:500])
            return []

        recommendations = []
        for rank, exp in enumerate(experiments_data[:top_n], 1):
            rec = ExperimentRecommendation(
                org_id=org_id,
                title=exp.get("title", "Untitled Experiment"),
                hypothesis=exp.get("hypothesis", ""),
                expected_impact=exp.get("expected_impact", ""),
                expected_revenue_impact=exp.get("expected_revenue_impact"),
                confidence=exp.get("confidence", 0.5),
                effort_estimate=exp.get("effort_estimate", "medium"),
                variants=exp.get("variants", {}),
                evidence_sources={"evidence": exp.get("evidence", [])},
                rank=rank,
                generated_at=datetime.now(timezone.utc),
            )
            self.db.add(rec)
            recommendations.append(rec)

        if recommendations:
            await self.db.commit()

        logger.info(
            "experiments_generated",
            org_id=str(org_id),
            count=len(recommendations),
        )
        return recommendations
