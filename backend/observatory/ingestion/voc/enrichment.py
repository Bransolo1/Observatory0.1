"""LLM enrichment pipeline for VoC feedback — sentiment, categorisation, embedding."""

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from observatory.core.llm.service import LLMService, ModelTier
from observatory.core.models.feedback import Feedback

logger = structlog.get_logger()

ENRICHMENT_SYSTEM_PROMPT = """You are a consumer feedback analyst. Analyse the following customer feedback and extract structured information.

You must respond with valid JSON matching this exact schema:
{
    "sentiment": "positive" | "negative" | "neutral" | "mixed",
    "sentiment_score": float between -1.0 and 1.0,
    "urgency": "low" | "medium" | "high" | "critical",
    "product_areas": ["list of product areas this relates to"],
    "themes": ["list of themes: e.g. 'performance', 'pricing', 'onboarding', 'ui', 'feature_request', 'bug'"],
    "summary": "One sentence summary of the core feedback"
}"""


class FeedbackEnricher:
    def __init__(self, llm: LLMService, db: AsyncSession):
        self.llm = llm
        self.db = db

    async def enrich_feedback(self, feedback: Feedback) -> Feedback:
        """Run LLM classification and embedding on a single feedback item."""
        text = f"{feedback.title or ''}\n\n{feedback.text}".strip()

        # Step 1: LLM classification
        try:
            result = await self.llm.extract_structured(
                text=text,
                schema_description=ENRICHMENT_SYSTEM_PROMPT,
                tier=ModelTier.CLASSIFICATION,
            )
            feedback.sentiment = result.get("sentiment")
            feedback.sentiment_score = result.get("sentiment_score")
            feedback.urgency = result.get("urgency")
            feedback.product_areas = result.get("product_areas", [])
            feedback.themes = result.get("themes", [])
            feedback.summary = result.get("summary")
        except Exception as e:
            logger.error("feedback_enrichment_llm_error", feedback_id=str(feedback.id), error=str(e))

        # Step 2: Generate embedding
        try:
            embeddings = await self.llm.embed([text])
            feedback.embedding = embeddings[0]
        except Exception as e:
            logger.error("feedback_embedding_error", feedback_id=str(feedback.id), error=str(e))

        feedback.enriched_at = datetime.now(timezone.utc)
        return feedback

    async def enrich_batch(self, org_id: uuid.UUID, batch_size: int = 50) -> int:
        """Enrich all un-enriched feedback for an org."""
        result = await self.db.execute(
            select(Feedback)
            .where(Feedback.org_id == org_id, Feedback.enriched_at.is_(None))
            .limit(batch_size)
        )
        items = result.scalars().all()

        enriched_count = 0
        for item in items:
            await self.enrich_feedback(item)
            enriched_count += 1

        if enriched_count > 0:
            await self.db.commit()

        logger.info("feedback_batch_enriched", org_id=str(org_id), count=enriched_count)
        return enriched_count
