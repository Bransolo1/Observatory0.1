"""Celery tasks for VoC ingestion pipeline."""

import asyncio
from datetime import datetime, timezone

import structlog

from observatory.core.tasks import app

logger = structlog.get_logger()


@app.task(name="observatory.ingestion.voc.tasks.sync_all_voc_sources")
def sync_all_voc_sources():
    """Sync all active VoC sources across all orgs."""
    asyncio.run(_sync_all_voc())


async def _sync_all_voc():
    from sqlalchemy import select

    from observatory.core.database import async_session_factory
    from observatory.core.llm import get_llm_service
    from observatory.core.models.feedback import Feedback
    from observatory.core.models.telemetry import TelemetryConnection
    from observatory.ingestion.voc.enrichment import FeedbackEnricher

    async with async_session_factory() as db:
        # Find all active VoC connections
        result = await db.execute(
            select(TelemetryConnection).where(
                TelemetryConnection.is_active.is_(True),
                TelemetryConnection.platform.in_(["zendesk", "intercom"]),
            )
        )
        connections = result.scalars().all()

        for conn in connections:
            try:
                connector = _get_connector(conn)
                if connector:
                    sync_result = await connector.sync(since=conn.last_sync_at)

                    # Persist normalized records
                    for record in getattr(sync_result, "_records", []):
                        feedback = Feedback(
                            org_id=conn.org_id,
                            source=record["source"],
                            source_id=record["source_id"],
                            source_url=record.get("source_url"),
                            title=record.get("title"),
                            text=record["text"],
                            author=record.get("author"),
                            metadata_=record.get("metadata", {}),
                            source_created_at=record.get("source_created_at"),
                        )
                        db.add(feedback)

                    conn.last_sync_at = datetime.now(timezone.utc)
                    conn.last_sync_status = "success" if sync_result.success else "error"
                    await db.commit()

                    # Enrich new feedback
                    llm = get_llm_service()
                    enricher = FeedbackEnricher(llm=llm, db=db)
                    await enricher.enrich_batch(conn.org_id)

            except Exception as e:
                logger.error(
                    "voc_sync_error",
                    connection_id=str(conn.id),
                    platform=conn.platform,
                    error=str(e),
                )
                conn.last_sync_status = "error"
                await db.commit()


def _get_connector(conn):
    from observatory.ingestion.voc.zendesk import ZendeskConnector

    if conn.platform == "zendesk":
        return ZendeskConnector(
            org_id=conn.org_id, credentials=conn.credentials, config=conn.config
        )
    return None
