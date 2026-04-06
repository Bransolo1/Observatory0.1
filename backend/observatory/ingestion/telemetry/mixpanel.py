"""Mixpanel connector — ingests funnel, retention, and event data."""

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
import structlog

from observatory.ingestion.base import BaseConnector, ConnectionStatus, SyncResult

logger = structlog.get_logger()


class MixpanelConnector(BaseConnector):
    """
    Connects to Mixpanel's Data Export and Query APIs.

    Required credentials:
        - project_id: str
        - service_account_username: str
        - service_account_secret: str

    Config options:
        - funnels: list[dict] — funnel IDs to track
        - retention_event: str — event for retention analysis
        - key_events: list[str] — events to aggregate
    """

    BASE_URL = "https://mixpanel.com/api"
    DATA_URL = "https://data.mixpanel.com/api/2.0"

    def __init__(self, org_id: uuid.UUID, credentials: dict[str, Any], config: dict[str, Any]):
        super().__init__(org_id, credentials, config)
        self.project_id = credentials["project_id"]
        self.auth = (credentials["service_account_username"], credentials["service_account_secret"])

    async def authenticate(self) -> ConnectionStatus:
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{self.BASE_URL}/app/me",
                    auth=self.auth,
                    headers={"Accept": "application/json"},
                    timeout=10.0,
                )
                if response.status_code == 200:
                    return ConnectionStatus(connected=True, message="Authenticated")
                return ConnectionStatus(connected=False, message=f"HTTP {response.status_code}")
            except httpx.HTTPError as e:
                return ConnectionStatus(connected=False, message=str(e))

    async def test_connection(self) -> bool:
        return (await self.authenticate()).connected

    async def get_schema(self) -> dict[str, Any]:
        return {
            "source": "mixpanel",
            "data_types": ["funnels", "retention", "events"],
            "fields": {
                "funnel_step": ["funnel_id", "step_name", "count", "conversion_rate", "date"],
                "retention": ["cohort_date", "day", "retention_rate", "count"],
                "event_aggregate": ["event_name", "count", "unique_users", "date"],
            },
        }

    async def sync(self, since: datetime | None = None) -> SyncResult:
        result = SyncResult()
        records = []

        from_date = since.date() if since else date.today() - timedelta(days=7)
        to_date = date.today()

        # Fetch funnel data
        funnels = self.config.get("funnels", [])
        for funnel_config in funnels:
            funnel_data = await self._fetch_funnel(funnel_config["id"], from_date, to_date)
            records.extend(funnel_data)

        # Fetch key event aggregates
        key_events = self.config.get("key_events", [])
        for event in key_events:
            event_data = await self._fetch_event_aggregate(event, from_date, to_date)
            records.extend(event_data)

        result.records_fetched = len(records)
        result.records_created = len(records)
        result.completed_at = datetime.now(timezone.utc)
        result._records = records  # type: ignore[attr-defined]

        logger.info("mixpanel_sync_complete", org_id=str(self.org_id), records=len(records))
        return result

    async def _fetch_funnel(
        self, funnel_id: str, from_date: date, to_date: date
    ) -> list[dict]:
        records = []
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{self.BASE_URL}/2.0/funnels",
                    params={
                        "funnel_id": funnel_id,
                        "from_date": from_date.isoformat(),
                        "to_date": to_date.isoformat(),
                        "unit": "day",
                    },
                    auth=self.auth,
                    headers={"Accept": "application/json"},
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()

                for date_str, steps in data.get("data", {}).items():
                    for step_name, step_data in steps.get("steps", {}).items():
                        records.append({
                            "metric_type": "funnel_step",
                            "metric_name": f"{funnel_id}_{step_name}",
                            "metric_date": date_str,
                            "value": step_data.get("conversion_rate", 0),
                            "sample_size": step_data.get("count", 0),
                            "dimensions": {"funnel_id": funnel_id, "step": step_name},
                            "source_platform": "mixpanel",
                        })
            except Exception as e:
                logger.error("mixpanel_funnel_error", funnel_id=funnel_id, error=str(e))

        return records

    async def _fetch_event_aggregate(
        self, event_name: str, from_date: date, to_date: date
    ) -> list[dict]:
        records = []
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{self.BASE_URL}/2.0/events",
                    params={
                        "event": [event_name],
                        "from_date": from_date.isoformat(),
                        "to_date": to_date.isoformat(),
                        "unit": "day",
                        "type": "general",
                    },
                    auth=self.auth,
                    headers={"Accept": "application/json"},
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()

                values = data.get("data", {}).get("values", {}).get(event_name, {})
                for date_str, count in values.items():
                    records.append({
                        "metric_type": "feature_usage",
                        "metric_name": event_name,
                        "metric_date": date_str,
                        "value": count,
                        "sample_size": count,
                        "dimensions": {"event": event_name},
                        "source_platform": "mixpanel",
                    })
            except Exception as e:
                logger.error("mixpanel_event_error", event=event_name, error=str(e))

        return records
