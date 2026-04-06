"""Research brief generator — creates structured research briefs from knowledge gaps."""

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from observatory.core.llm import get_llm_service
from observatory.core.models.research import ResearchBrief

logger = structlog.get_logger()

# Cost estimates by methodology
METHODOLOGY_COSTS = {
    "survey": {"min": 2000, "max": 8000, "currency": "GBP"},
    "interview": {"min": 3000, "max": 12000, "currency": "GBP"},
    "usability_test": {"min": 4000, "max": 15000, "currency": "GBP"},
    "diary_study": {"min": 5000, "max": 20000, "currency": "GBP"},
    "a_b_test": {"min": 500, "max": 3000, "currency": "GBP"},
}


class ResearchBriefGenerator:
    """Generates structured research briefs from knowledge gaps."""

    def __init__(self, db: AsyncSession, org_id: uuid.UUID):
        self.db = db
        self.org_id = org_id
        self.llm = get_llm_service()

    async def generate_brief(self, gap: dict[str, Any]) -> ResearchBrief:
        """Generate a full research brief from a knowledge gap."""
        methodology = gap.get("methodology", "survey")
        cost_range = METHODOLOGY_COSTS.get(methodology, METHODOLOGY_COSTS["survey"])

        # Generate detailed brief content via LLM
        brief_content = await self._generate_brief_content(gap)

        brief = ResearchBrief(
            org_id=self.org_id,
            title=gap.get("title", "Untitled Research Brief"),
            knowledge_gap=gap.get("description", ""),
            objective=brief_content.get("objective", ""),
            methodology=methodology,
            sample_description=brief_content.get("sample_description", ""),
            sample_size=brief_content.get("sample_size", 0),
            estimated_cost=float(cost_range["min"] + cost_range["max"]) / 2,
            estimated_cost_currency=cost_range["currency"],
            expected_value=gap.get("estimated_value", ""),
            expected_value_rationale=brief_content.get("value_rationale", ""),
            product_area=gap.get("related_area"),
            priority=gap.get("priority", "medium"),
            status="draft",
            evidence_sources=brief_content.get("evidence_sources", {}),
        )

        self.db.add(brief)
        await self.db.commit()
        await self.db.refresh(brief)

        logger.info(
            "research_brief_generated",
            org_id=str(self.org_id),
            brief_id=str(brief.id),
            title=brief.title,
        )
        return brief

    async def _generate_brief_content(self, gap: dict[str, Any]) -> dict[str, Any]:
        """Use LLM to flesh out research brief details."""
        prompt = (
            "Generate a detailed research brief for the following knowledge gap:\n\n"
            f"TITLE: {gap.get('title', '')}\n"
            f"DESCRIPTION: {gap.get('description', '')}\n"
            f"METHODOLOGY: {gap.get('methodology', 'survey')}\n"
            f"PRODUCT AREA: {gap.get('related_area', '')}\n\n"
            "Provide in this format:\n"
            "OBJECTIVE: <clear research objective in 1-2 sentences>\n"
            "SAMPLE_DESCRIPTION: <who to recruit, demographics, criteria>\n"
            "SAMPLE_SIZE: <recommended number of participants as integer>\n"
            "VALUE_RATIONALE: <why this research is worth the investment, tie to business outcomes>\n"
            "QUESTIONS: <3-5 key research questions, one per line starting with - >\n"
            "SUCCESS_CRITERIA: <how we'll know the research was valuable>"
        )

        try:
            response = await self.llm.complete(prompt=prompt, tier="DEFAULT")
            return self._parse_brief_content(response)
        except Exception as e:
            logger.error("brief_generation_error", error=str(e))
            return {
                "objective": gap.get("description", ""),
                "sample_description": "To be determined",
                "sample_size": 10,
                "value_rationale": gap.get("estimated_value", ""),
                "evidence_sources": {},
            }

    def _parse_brief_content(self, response: str) -> dict[str, Any]:
        """Parse LLM response into structured brief content."""
        content: dict[str, Any] = {}
        questions = []

        for line in response.split("\n"):
            line = line.strip()
            if line.startswith("OBJECTIVE:"):
                content["objective"] = line.replace("OBJECTIVE:", "").strip()
            elif line.startswith("SAMPLE_DESCRIPTION:"):
                content["sample_description"] = line.replace("SAMPLE_DESCRIPTION:", "").strip()
            elif line.startswith("SAMPLE_SIZE:"):
                try:
                    size_str = line.replace("SAMPLE_SIZE:", "").strip()
                    content["sample_size"] = int("".join(c for c in size_str if c.isdigit()) or "10")
                except (ValueError, IndexError):
                    content["sample_size"] = 10
            elif line.startswith("VALUE_RATIONALE:"):
                content["value_rationale"] = line.replace("VALUE_RATIONALE:", "").strip()
            elif line.startswith("- "):
                questions.append(line[2:].strip())
            elif line.startswith("SUCCESS_CRITERIA:"):
                content["success_criteria"] = line.replace("SUCCESS_CRITERIA:", "").strip()

        content["evidence_sources"] = {"research_questions": questions}
        return content

    async def generate_briefs_from_gaps(
        self, gaps: list[dict[str, Any]]
    ) -> list[ResearchBrief]:
        """Generate research briefs for multiple knowledge gaps."""
        briefs = []
        for gap in gaps:
            brief = await self.generate_brief(gap)
            briefs.append(brief)
        return briefs
