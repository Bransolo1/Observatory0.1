"""Celery tasks for digest generation."""

import asyncio

import structlog

from observatory.core.tasks import app

logger = structlog.get_logger()


@app.task(name="observatory.output.digests.tasks.generate_weekly_digests")
def generate_weekly_digests():
    """Generate weekly digests for all active orgs."""
    asyncio.run(_generate_all_weekly())


async def _generate_all_weekly():
    from sqlalchemy import select

    from observatory.core.database import async_session_factory
    from observatory.core.llm import get_llm_service
    from observatory.core.models.organization import Organization
    from observatory.output.digests.generator import DigestGenerator

    async with async_session_factory() as db:
        result = await db.execute(
            select(Organization).where(Organization.is_active.is_(True))
        )
        orgs = result.scalars().all()

        llm = get_llm_service()
        for org in orgs:
            try:
                generator = DigestGenerator(llm=llm, db=db)
                digest = await generator.generate_weekly_digest(org.id)
                # TODO: deliver via email/Slack based on org notification preferences
                logger.info("weekly_digest_delivered", org_id=str(org.id))
            except Exception as e:
                logger.error("weekly_digest_error", org_id=str(org.id), error=str(e))
