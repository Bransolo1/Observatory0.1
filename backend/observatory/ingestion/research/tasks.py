"""Celery tasks for research pipeline."""

import structlog
from celery import shared_task

from observatory.core.database import async_session_factory

logger = structlog.get_logger()


@shared_task(name="observatory.ingestion.research.tasks.detect_knowledge_gaps")
def detect_knowledge_gaps(org_id: str) -> dict:
    """Detect knowledge gaps for an organization."""
    import asyncio
    import uuid

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_detect_gaps_async(uuid.UUID(org_id)))
    finally:
        loop.close()


async def _detect_gaps_async(org_id) -> dict:
    from observatory.ingestion.research.gap_detector import KnowledgeGapDetector

    async with async_session_factory() as db:
        detector = KnowledgeGapDetector(db=db, org_id=org_id)
        gaps = await detector.detect_gaps()
        return {
            "org_id": str(org_id),
            "gaps_found": len(gaps),
            "gaps": gaps,
        }


@shared_task(name="observatory.ingestion.research.tasks.generate_research_briefs")
def generate_research_briefs(org_id: str, gaps: list) -> dict:
    """Generate research briefs from detected knowledge gaps."""
    import asyncio
    import uuid

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            _generate_briefs_async(uuid.UUID(org_id), gaps)
        )
    finally:
        loop.close()


async def _generate_briefs_async(org_id, gaps: list) -> dict:
    from observatory.output.briefs.generator import ResearchBriefGenerator

    async with async_session_factory() as db:
        generator = ResearchBriefGenerator(db=db, org_id=org_id)
        briefs = await generator.generate_briefs_from_gaps(gaps)
        return {
            "org_id": str(org_id),
            "briefs_generated": len(briefs),
            "brief_ids": [str(b.id) for b in briefs],
        }
