"""Hacker News connector — monitors HN for relevant mentions and discussions."""

import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from observatory.ingestion.base import BaseConnector, ConnectionStatus, SyncResult

logger = structlog.get_logger()


class HackerNewsConnector(BaseConnector):
    """
    Monitors Hacker News for mentions via the Algolia HN Search API.

    Required credentials: (none — public API)

    Config options:
        - search_terms: list[str] — keywords to search
        - competitor_names: list[str] — competitor names to track
        - max_results: int — max results per search term (default: 50)
    """

    SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"

    def __init__(self, org_id: uuid.UUID, credentials: dict[str, Any], config: dict[str, Any]):
        super().__init__(org_id, credentials, config)
        self.search_terms = config.get("search_terms", [])
        self.competitor_names = config.get("competitor_names", [])
        self.max_results = config.get("max_results", 50)

    async def authenticate(self) -> ConnectionStatus:
        return ConnectionStatus(connected=True, message="HN API requires no authentication")

    async def test_connection(self) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    self.SEARCH_URL, params={"query": "test", "hitsPerPage": 1}, timeout=10
                )
                return resp.status_code == 200
        except Exception:
            return False

    async def get_schema(self) -> dict[str, Any]:
        return {
            "source": "hackernews",
            "data_types": ["stories", "comments"],
            "fields": {
                "item": ["objectID", "title", "text", "author", "points", "url", "created_at"],
            },
        }

    async def sync(self, since: datetime | None = None) -> SyncResult:
        result = SyncResult()
        mentions: list[dict] = []

        for term in self.search_terms:
            items = await self._search(term, since)
            mentions.extend(items)

        # Deduplicate
        seen = set()
        unique = []
        for m in mentions:
            if m["source_id"] not in seen:
                seen.add(m["source_id"])
                unique.append(m)

        # Tag competitor mentions
        for mention in unique:
            text = f"{mention.get('title', '')} {mention.get('text', '')}".lower()
            for comp in self.competitor_names:
                if comp.lower() in text:
                    mention["mentions_competitor"] = comp
                    break

        result.records_fetched = len(unique)
        result.records_created = len(unique)
        result.completed_at = datetime.now(timezone.utc)
        result._records = unique  # type: ignore[attr-defined]

        logger.info("hn_sync_complete", org_id=str(self.org_id), mentions=len(unique))
        return result

    async def _search(self, query: str, since: datetime | None) -> list[dict]:
        items = []
        try:
            params: dict[str, Any] = {
                "query": query,
                "hitsPerPage": self.max_results,
                "tags": "(story,comment)",
            }
            if since:
                params["numericFilters"] = f"created_at_i>{int(since.timestamp())}"

            async with httpx.AsyncClient() as client:
                resp = await client.get(self.SEARCH_URL, params=params, timeout=15)
                resp.raise_for_status()
                data = resp.json()

                for hit in data.get("hits", []):
                    title = hit.get("title") or hit.get("story_title") or ""
                    text = hit.get("comment_text") or hit.get("story_text") or ""
                    items.append({
                        "platform": "hackernews",
                        "source_id": hit.get("objectID", ""),
                        "source_url": f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}",
                        "author": hit.get("author"),
                        "text": f"{title}\n\n{text}".strip(),
                        "topics": [],
                        "engagement_score": hit.get("points") or hit.get("num_comments") or 0,
                        "posted_at": hit.get("created_at", datetime.now(timezone.utc).isoformat()),
                        "metadata": {
                            "type": "story" if hit.get("title") else "comment",
                            "points": hit.get("points", 0),
                            "num_comments": hit.get("num_comments", 0),
                            "story_url": hit.get("url"),
                        },
                    })
        except Exception as e:
            logger.error("hn_search_error", query=query, error=str(e))

        return items
