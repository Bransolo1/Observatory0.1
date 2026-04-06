"""Celery tasks for friction detection."""

import asyncio

import structlog

from observatory.core.tasks import app

logger = structlog.get_logger()


@app.task(name="observatory.analysis.friction.tasks.detect_friction_signals")
def detect_friction_signals():
    """Nightly friction detection across all orgs."""
    asyncio.run(_detect_all())


async def _detect_all():
    from sqlalchemy import select

    from observatory.core.database import async_session_factory
    from observatory.core.llm import get_llm_service
    from observatory.core.models.organization import Organization
    from observatory.analysis.friction.detector import FrictionDetector

    async with async_session_factory() as db:
        result = await db.execute(
            select(Organization).where(Organization.is_active.is_(True))
        )
        orgs = result.scalars().all()

        llm = get_llm_service()
        for org in orgs:
            try:
                detector = FrictionDetector(llm=llm, db=db)
                insights = await detector.run_detection_cycle(org.id)
                logger.info(
                    "org_friction_detection_done",
                    org_id=str(org.id),
                    insights=len(insights),
                )
            except Exception as e:
                logger.error(
                    "org_friction_detection_error", org_id=str(org.id), error=str(e)
                )
