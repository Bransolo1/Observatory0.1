"""Website change detector — monitors competitor pages for pricing, feature, and UX changes."""

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from observatory.core.llm.service import LLMService, ModelTier
from observatory.ingestion.base import BaseConnector, ConnectionStatus, SyncResult

logger = structlog.get_logger()

CHANGE_ANALYSIS_PROMPT = """Analyse the differences between two snapshots of a competitor's web page.

Previous snapshot:
{previous}

Current snapshot:
{current}

Identify concrete changes and classify each as one of: pricing, feature, ux, messaging, promotion, other.
Rate significance as: low, medium, high, critical.

Respond with valid JSON array:
[{{
    "change_type": "pricing|feature|ux|messaging|promotion|other",
    "title": "Short description of the change",
    "description": "Detailed explanation of what changed and its potential impact",
    "significance": "low|medium|high|critical"
}}]

If no meaningful changes, return an empty array: []"""


class WebsiteMonitorConnector(BaseConnector):
    """
    Monitors competitor websites for changes by comparing page content snapshots.

    Required credentials: (none — public web pages)

    Config options:
        - urls: list[dict] — pages to monitor, each with:
            - url: str
            - label: str (e.g., "pricing", "features", "homepage")
            - selector: str | None — CSS selector to focus on (optional)
        - user_agent: str — custom user agent (optional)
    """

    def __init__(
        self,
        org_id: uuid.UUID,
        credentials: dict[str, Any],
        config: dict[str, Any],
        llm: LLMService | None = None,
    ):
        super().__init__(org_id, credentials, config)
        self.urls = config.get("urls", [])
        self.user_agent = config.get(
            "user_agent",
            "Mozilla/5.0 (compatible; Observatory/1.0; +https://observatory.internal)",
        )
        self.llm = llm
        self._previous_snapshots: dict[str, str] = {}

    async def authenticate(self) -> ConnectionStatus:
        return ConnectionStatus(connected=True, message="No authentication required")

    async def test_connection(self) -> bool:
        if not self.urls:
            return False
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.head(
                    self.urls[0]["url"],
                    headers={"User-Agent": self.user_agent},
                    timeout=10,
                    follow_redirects=True,
                )
                return resp.status_code < 400
        except Exception:
            return False

    async def get_schema(self) -> dict[str, Any]:
        return {
            "source": "website_monitor",
            "data_types": ["page_snapshots", "detected_changes"],
            "fields": {
                "snapshot": ["url", "label", "content_hash", "text_content", "fetched_at"],
                "change": ["change_type", "title", "description", "significance"],
            },
        }

    async def sync(self, since: datetime | None = None) -> SyncResult:
        result = SyncResult()
        detected_changes: list[dict] = []

        for url_config in self.urls:
            try:
                url = url_config["url"]
                label = url_config.get("label", "page")

                current_text = await self._fetch_page_text(url)
                if not current_text:
                    continue

                result.records_fetched += 1
                current_hash = hashlib.sha256(current_text.encode()).hexdigest()
                previous_text = self._previous_snapshots.get(url)

                if previous_text and previous_text != current_text and self.llm:
                    # Content changed — use LLM to analyse what changed
                    changes = await self._analyse_changes(
                        previous_text[:5000], current_text[:5000], label
                    )
                    for change in changes:
                        change["source_url"] = url
                        change["page_label"] = label
                        detected_changes.append(change)

                self._previous_snapshots[url] = current_text

            except Exception as e:
                logger.error("website_monitor_error", url=url_config.get("url"), error=str(e))
                result.errors.append(str(e))

        result.records_created = len(detected_changes)
        result.completed_at = datetime.now(timezone.utc)
        result._records = detected_changes  # type: ignore[attr-defined]

        logger.info(
            "website_monitor_sync_complete",
            org_id=str(self.org_id),
            pages_checked=result.records_fetched,
            changes_detected=len(detected_changes),
        )
        return result

    async def _fetch_page_text(self, url: str) -> str | None:
        """Fetch page and extract text content."""
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    url,
                    headers={"User-Agent": self.user_agent},
                    timeout=20,
                    follow_redirects=True,
                )
                response.raise_for_status()
                # Basic HTML text extraction — strip tags
                import re

                html = response.text
                text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
                text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
                text = re.sub(r"<[^>]+>", " ", text)
                text = re.sub(r"\s+", " ", text).strip()
                return text
            except Exception as e:
                logger.error("page_fetch_error", url=url, error=str(e))
                return None

    async def _analyse_changes(
        self, previous: str, current: str, label: str
    ) -> list[dict]:
        """Use LLM to identify and classify changes between snapshots."""
        import json

        try:
            prompt = CHANGE_ANALYSIS_PROMPT.format(previous=previous, current=current)
            response = await self.llm.complete(  # type: ignore[union-attr]
                prompt=prompt,
                system=f"You are analysing changes to a competitor's {label} page.",
                tier=ModelTier.DEFAULT,
                temperature=0.2,
                use_cache=False,
            )
            return json.loads(response)
        except Exception as e:
            logger.error("change_analysis_error", label=label, error=str(e))
            return []
