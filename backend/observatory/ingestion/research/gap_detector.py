"""Knowledge gap detector — identifies blind spots in current intelligence coverage."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from observatory.core.llm import get_llm_service
from observatory.core.models.feedback import Feedback
from observatory.core.models.insight import Insight, PriorityScore
from observatory.core.models.knowledge import KnowledgeDocument
from observatory.core.models.telemetry import FrictionSignal

logger = structlog.get_logger()


class KnowledgeGapDetector:
    """Analyzes current data coverage and identifies blind spots."""

    def __init__(self, db: AsyncSession, org_id: uuid.UUID):
        self.db = db
        self.org_id = org_id
        self.llm = get_llm_service()

    async def detect_gaps(self) -> list[dict[str, Any]]:
        """Run full gap detection analysis."""
        # Gather current coverage data
        coverage = await self._assess_coverage()

        # Identify gaps via LLM
        gaps = await self._identify_gaps(coverage)

        logger.info(
            "knowledge_gaps_detected",
            org_id=str(self.org_id),
            gaps_found=len(gaps),
        )
        return gaps

    async def _assess_coverage(self) -> dict[str, Any]:
        """Assess what intelligence we currently have."""
        since_90d = datetime.now(timezone.utc) - timedelta(days=90)

        # Knowledge documents
        doc_result = await self.db.execute(
            select(
                KnowledgeDocument.doc_type,
                func.count(KnowledgeDocument.id),
            )
            .where(KnowledgeDocument.org_id == self.org_id)
            .group_by(KnowledgeDocument.doc_type)
        )
        doc_coverage = {row[0]: row[1] for row in doc_result.all()}

        # Feedback themes
        feedback_result = await self.db.execute(
            select(func.count(Feedback.id)).where(
                Feedback.org_id == self.org_id,
                Feedback.created_at >= since_90d,
            )
        )
        feedback_count = feedback_result.scalar() or 0

        # Friction signals
        friction_result = await self.db.execute(
            select(FrictionSignal.product_area, func.count(FrictionSignal.id))
            .where(
                FrictionSignal.org_id == self.org_id,
                FrictionSignal.detected_at >= since_90d,
            )
            .group_by(FrictionSignal.product_area)
        )
        friction_areas = {row[0]: row[1] for row in friction_result.all() if row[0]}

        # Priority scores — high priority areas
        priority_result = await self.db.execute(
            select(PriorityScore.product_area, PriorityScore.score)
            .where(PriorityScore.org_id == self.org_id)
            .order_by(PriorityScore.score.desc())
            .limit(10)
        )
        priority_areas = [
            {"area": row[0], "score": row[1]} for row in priority_result.all()
        ]

        # Insights
        insight_result = await self.db.execute(
            select(func.count(Insight.id)).where(
                Insight.org_id == self.org_id,
                Insight.created_at >= since_90d,
            )
        )
        insight_count = insight_result.scalar() or 0

        return {
            "document_types": doc_coverage,
            "feedback_count_90d": feedback_count,
            "friction_areas": friction_areas,
            "priority_areas": priority_areas,
            "insight_count_90d": insight_count,
        }

    async def _identify_gaps(self, coverage: dict[str, Any]) -> list[dict[str, Any]]:
        """Use LLM to identify knowledge gaps from coverage analysis."""
        prompt = (
            "You are an intelligence analyst identifying knowledge gaps for a product organization.\n\n"
            f"CURRENT COVERAGE:\n"
            f"- Knowledge documents by type: {coverage['document_types']}\n"
            f"- Customer feedback items (90 days): {coverage['feedback_count_90d']}\n"
            f"- Friction signal areas: {coverage['friction_areas']}\n"
            f"- Top priority areas: {coverage['priority_areas']}\n"
            f"- Insights generated (90 days): {coverage['insight_count_90d']}\n\n"
            "Identify 3-5 knowledge gaps where primary research would be most valuable. "
            "For each gap, provide in this exact format (one per block, separated by ---):\n"
            "GAP: <short title>\n"
            "DESCRIPTION: <what we don't know and why it matters>\n"
            "METHODOLOGY: <survey / interview / usability_test / diary_study / a_b_test>\n"
            "PRIORITY: <high / medium / low>\n"
            "ESTIMATED_VALUE: <what we'd gain from this knowledge>\n"
            "RELATED_AREA: <product area this relates to>\n"
            "---"
        )

        try:
            response = await self.llm.complete(prompt=prompt, tier="SYNTHESIS")
            return self._parse_gaps(response)
        except Exception as e:
            logger.error("gap_detection_error", error=str(e))
            return []

    def _parse_gaps(self, response: str) -> list[dict[str, Any]]:
        """Parse LLM response into structured gap objects."""
        gaps = []
        blocks = response.split("---")

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            gap: dict[str, Any] = {}
            for line in block.split("\n"):
                line = line.strip()
                if line.startswith("GAP:"):
                    gap["title"] = line.replace("GAP:", "").strip()
                elif line.startswith("DESCRIPTION:"):
                    gap["description"] = line.replace("DESCRIPTION:", "").strip()
                elif line.startswith("METHODOLOGY:"):
                    gap["methodology"] = line.replace("METHODOLOGY:", "").strip()
                elif line.startswith("PRIORITY:"):
                    gap["priority"] = line.replace("PRIORITY:", "").strip().lower()
                elif line.startswith("ESTIMATED_VALUE:"):
                    gap["estimated_value"] = line.replace("ESTIMATED_VALUE:", "").strip()
                elif line.startswith("RELATED_AREA:"):
                    gap["related_area"] = line.replace("RELATED_AREA:", "").strip()

            if gap.get("title"):
                gaps.append(gap)

        return gaps
