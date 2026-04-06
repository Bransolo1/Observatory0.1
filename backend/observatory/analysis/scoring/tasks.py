"""Celery tasks for priority scoring."""

import asyncio

import structlog

from observatory.core.tasks import app

logger = structlog.get_logger()


@app.task(name="observatory.analysis.scoring.tasks.recalculate_priority_scores")
def recalculate_priority_scores():
    """Nightly recalculation of priority scores."""
    asyncio.run(_recalculate_all())


async def _recalculate_all():
    from sqlalchemy import select

    from observatory.core.database import async_session_factory
    from observatory.core.llm import get_llm_service
    from observatory.core.models.organization import Organization
    from observatory.analysis.scoring.engine import PriorityScoringEngine

    async with async_session_factory() as db:
        result = await db.execute(
            select(Organization).where(Organization.is_active.is_(True))
        )
        orgs = result.scalars().all()

        llm = get_llm_service()
        for org in orgs:
            try:
                engine = PriorityScoringEngine(llm=llm, db=db)
                scores = await engine.recalculate_all(org.id)
                logger.info("org_scores_done", org_id=str(org.id), count=len(scores))
            except Exception as e:
                logger.error("org_scores_error", org_id=str(org.id), error=str(e))
