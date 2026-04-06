"""Celery tasks for telemetry ingestion."""

import asyncio
from datetime import datetime, timezone

import structlog

from observatory.core.tasks import app

logger = structlog.get_logger()


@app.task(name="observatory.ingestion.telemetry.tasks.sync_all_telemetry")
def sync_all_telemetry():
    """Nightly sync of all telemetry sources."""
    asyncio.run(_sync_all())


async def _sync_all():
    from sqlalchemy import select

    from observatory.core.database import async_session_factory
    from observatory.core.models.telemetry import TelemetryAggregate, TelemetryConnection
    from observatory.ingestion.telemetry.mixpanel import MixpanelConnector

    async with async_session_factory() as db:
        result = await db.execute(
            select(TelemetryConnection).where(
                TelemetryConnection.is_active.is_(True),
                TelemetryConnection.platform.in_(["mixpanel", "amplitude"]),
            )
        )
        connections = result.scalars().all()

        for conn in connections:
            try:
                connector = None
                if conn.platform == "mixpanel":
                    connector = MixpanelConnector(
                        org_id=conn.org_id, credentials=conn.credentials, config=conn.config
                    )

                if connector:
                    sync_result = await connector.sync(since=conn.last_sync_at)

                    for record in getattr(sync_result, "_records", []):
                        aggregate = TelemetryAggregate(
                            org_id=conn.org_id,
                            metric_date=record["metric_date"],
                            metric_type=record["metric_type"],
                            metric_name=record["metric_name"],
                            value=record["value"],
                            sample_size=record.get("sample_size", 0),
                            dimensions=record.get("dimensions", {}),
                            source_platform=record["source_platform"],
                        )
                        db.add(aggregate)

                    conn.last_sync_at = datetime.now(timezone.utc)
                    conn.last_sync_status = "success" if sync_result.success else "error"
                    await db.commit()

            except Exception as e:
                logger.error(
                    "telemetry_sync_error",
                    connection_id=str(conn.id),
                    platform=conn.platform,
                    error=str(e),
                )
