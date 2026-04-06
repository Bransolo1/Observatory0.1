"""Amplitude connector — ingests funnel, retention, and event data."""

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
import structlog

from observatory.ingestion.base import BaseConnector, ConnectionStatus, SyncResult

logger = structlog.get_logger()


class AmplitudeConnector(BaseConnector):
    """
    Connects to Amplitude's Dashboard REST API and Export API.

    Required credentials:
        - api_key: str
        - secret_key: str

    Config options:
        - funnels: list[dict] — funnel IDs to track (each with "id" and "name")
        - key_events: list[str] — event names to aggregate
        - retention_event: str | None — event for retention analysis
    """

    BASE_URL = "https://amplitude.com/api/2"

    def __init__(self, org_id: uuid.UUID, credentials: dict[str, Any], config: dict[str, Any]):
        super().__init__(org_id, credentials, config)
        self.api_key = credentials["api_key"]
        self.secret_key = credentials["secret_key"]
        self.auth = (self.api_key, self.secret_key)

    async def authenticate(self) -> ConnectionStatus:
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    f"{self.BASE_URL}/events/segmentation",
                    params={
                        "e": '{"event_type":"_active"}',
                        "start": date.today().isoformat().replace("-", ""),
                        "end": date.today().isoformat().replace("-", ""),
                    },
                    auth=self.auth,
                    timeout=10,
                )
                if resp.status_code == 200:
                    return ConnectionStatus(connected=True, message="Authenticated with Amplitude")
                return ConnectionStatus(connected=False, message=f"HTTP {resp.status_code}")
            except httpx.HTTPError as e:
                return ConnectionStatus(connected=False, message=str(e))

    async def test_connection(self) -> bool:
        return (await self.authenticate()).connected

    async def get_schema(self) -> dict[str, Any]:
        return {
            "source": "amplitude",
            "data_types": ["funnels", "retention", "events"],
            "fields": {
                "funnel_step": ["funnel_id", "step_name", "conversion_rate", "count", "date"],
                "event_aggregate": ["event_name", "count", "date"],
                "retention": ["cohort_date", "day", "retention_rate"],
            },
        }

    async def sync(self, since: datetime | None = None) -> SyncResult:
        result = SyncResult()
        records: list[dict] = []

        from_date = since.date() if since else date.today() - timedelta(days=7)
        to_date = date.today()

        start = from_date.isoformat().replace("-", "")
        end = to_date.isoformat().replace("-", "")

        # Fetch funnel data
        for funnel_config in self.config.get("funnels", []):
            funnel_data = await self._fetch_funnel(funnel_config, start, end)
            records.extend(funnel_data)

        # Fetch event aggregates
        for event_name in self.config.get("key_events", []):
            event_data = await self._fetch_event_segmentation(event_name, start, end)
            records.extend(event_data)

        # Fetch retention
        retention_event = self.config.get("retention_event")
        if retention_event:
            retention_data = await self._fetch_retention(retention_event, start, end)
            records.extend(retention_data)

        result.records_fetched = len(records)
        result.records_created = len(records)
        result.completed_at = datetime.now(timezone.utc)
        result._records = records  # type: ignore[attr-defined]

        logger.info("amplitude_sync_complete", org_id=str(self.org_id), records=len(records))
        return result

    async def _fetch_funnel(self, funnel_config: dict, start: str, end: str) -> list[dict]:
        records = []
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.BASE_URL}/funnels",
                    params={"fs": funnel_config["id"], "start": start, "end": end},
                    auth=self.auth,
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json().get("data", {})

                for date_str, day_data in data.items():
                    steps = day_data.get("steps", [])
                    for i, step in enumerate(steps):
                        records.append({
                            "metric_type": "funnel_step",
                            "metric_name": f"{funnel_config['name']}_step_{i}",
                            "metric_date": date_str,
                            "value": step.get("stepConversionRate", 0),
                            "sample_size": step.get("enteredCount", 0),
                            "dimensions": {
                                "funnel_id": funnel_config["id"],
                                "funnel_name": funnel_config["name"],
                                "step_index": i,
                                "step_event": step.get("eventName", ""),
                            },
                            "source_platform": "amplitude",
                        })
        except Exception as e:
            logger.error("amplitude_funnel_error", funnel=funnel_config.get("name"), error=str(e))

        return records

    async def _fetch_event_segmentation(
        self, event_name: str, start: str, end: str
    ) -> list[dict]:
        records = []
        try:
            import json

            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.BASE_URL}/events/segmentation",
                    params={
                        "e": json.dumps({"event_type": event_name}),
                        "start": start,
                        "end": end,
                    },
                    auth=self.auth,
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json().get("data", {})
                series = data.get("series", [[]])
                x_values = data.get("xValues", [])

                if series and series[0]:
                    for i, value in enumerate(series[0]):
                        date_str = x_values[i] if i < len(x_values) else start
                        records.append({
                            "metric_type": "feature_usage",
                            "metric_name": event_name,
                            "metric_date": date_str,
                            "value": value,
                            "sample_size": int(value),
                            "dimensions": {"event": event_name},
                            "source_platform": "amplitude",
                        })
        except Exception as e:
            logger.error("amplitude_event_error", event=event_name, error=str(e))

        return records

    async def _fetch_retention(self, event_name: str, start: str, end: str) -> list[dict]:
        records = []
        try:
            import json

            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.BASE_URL}/retention",
                    params={
                        "se": json.dumps({"event_type": event_name}),
                        "re": json.dumps({"event_type": event_name}),
                        "start": start,
                        "end": end,
                    },
                    auth=self.auth,
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json().get("data", {})

                for date_str, cohort in data.items():
                    for day, values in enumerate(cohort.get("combined", {}).get("counts", [])):
                        if values and cohort.get("combined", {}).get("outof", 0) > 0:
                            retention_rate = values / cohort["combined"]["outof"]
                            records.append({
                                "metric_type": "retention",
                                "metric_name": f"retention_day_{day}",
                                "metric_date": date_str,
                                "value": retention_rate,
                                "sample_size": cohort["combined"]["outof"],
                                "dimensions": {
                                    "cohort_date": date_str,
                                    "day": day,
                                    "event": event_name,
                                },
                                "source_platform": "amplitude",
                            })
        except Exception as e:
            logger.error("amplitude_retention_error", event=event_name, error=str(e))

        return records
