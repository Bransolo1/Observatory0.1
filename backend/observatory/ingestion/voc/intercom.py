"""Intercom connector — ingests conversations as VoC feedback."""

import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from observatory.ingestion.base import BaseConnector, ConnectionStatus, SyncResult

logger = structlog.get_logger()


class IntercomConnector(BaseConnector):
    """
    Connects to Intercom API to pull conversations, ratings, and tags.

    Required credentials:
        - access_token: str (Intercom API access token)

    Config options:
        - include_admin_replies: bool (default: False)
        - tag_filter: list[str] | None — only sync conversations with these tags
    """

    BASE_URL = "https://api.intercom.io"

    def __init__(self, org_id: uuid.UUID, credentials: dict[str, Any], config: dict[str, Any]):
        super().__init__(org_id, credentials, config)
        self.access_token = credentials["access_token"]
        self.include_admin_replies = config.get("include_admin_replies", False)
        self.tag_filter = config.get("tag_filter")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
            "Intercom-Version": "2.11",
        }

    async def authenticate(self) -> ConnectionStatus:
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    f"{self.BASE_URL}/me", headers=self._headers(), timeout=10
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return ConnectionStatus(
                        connected=True,
                        message=f"Authenticated as {data.get('name', 'Unknown')}",
                        metadata={"app_id": data.get("app", {}).get("id_code")},
                    )
                return ConnectionStatus(connected=False, message=f"HTTP {resp.status_code}")
            except httpx.HTTPError as e:
                return ConnectionStatus(connected=False, message=str(e))

    async def test_connection(self) -> bool:
        return (await self.authenticate()).connected

    async def get_schema(self) -> dict[str, Any]:
        return {
            "source": "intercom",
            "data_types": ["conversations", "conversation_parts"],
            "fields": {
                "conversation": [
                    "id", "title", "body", "state", "rating",
                    "tags", "author", "created_at",
                ],
            },
        }

    async def sync(self, since: datetime | None = None) -> SyncResult:
        result = SyncResult()
        normalized: list[dict] = []

        try:
            conversations = await self._fetch_conversations(since)
            result.records_fetched = len(conversations)

            for conv in conversations:
                feedback = self._normalize_conversation(conv)
                if feedback:
                    normalized.append(feedback)

                # Fetch conversation parts (messages)
                parts = await self._fetch_conversation_parts(conv["id"])
                for part in parts:
                    if not self.include_admin_replies and part.get("part_type") == "admin_reply":
                        continue
                    part_feedback = self._normalize_part(conv, part)
                    if part_feedback:
                        normalized.append(part_feedback)

            result.records_created = len(normalized)
            result.completed_at = datetime.now(timezone.utc)
            result._records = normalized  # type: ignore[attr-defined]

            logger.info(
                "intercom_sync_complete",
                org_id=str(self.org_id),
                conversations=result.records_fetched,
                feedback_items=len(normalized),
            )
        except Exception as e:
            logger.error("intercom_sync_error", error=str(e))
            result.errors.append(str(e))

        return result

    async def _fetch_conversations(self, since: datetime | None = None) -> list[dict]:
        conversations = []
        url = f"{self.BASE_URL}/conversations"
        params: dict[str, Any] = {"per_page": 50, "order": "desc", "sort": "updated_at"}

        async with httpx.AsyncClient() as client:
            while url:
                resp = await client.get(url, headers=self._headers(), params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()

                for conv in data.get("conversations", []):
                    updated = conv.get("updated_at")
                    if since and updated and updated < int(since.timestamp()):
                        return conversations
                    conversations.append(conv)

                pages = data.get("pages", {})
                next_page = pages.get("next")
                url = next_page.get("url") if next_page else None
                params = {}

        return conversations

    async def _fetch_conversation_parts(self, conversation_id: str) -> list[dict]:
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    f"{self.BASE_URL}/conversations/{conversation_id}",
                    headers=self._headers(),
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("conversation_parts", {}).get("conversation_parts", [])
            except Exception as e:
                logger.error("intercom_parts_error", conv_id=conversation_id, error=str(e))
                return []

    def _normalize_conversation(self, conv: dict) -> dict | None:
        source = conv.get("source", {})
        body = source.get("body") or ""
        if not body.strip():
            return None

        # Strip HTML from body
        import re
        clean_body = re.sub(r"<[^>]+>", " ", body)
        clean_body = re.sub(r"\s+", " ", clean_body).strip()

        rating = conv.get("conversation_rating", {})
        tags = [t.get("name") for t in conv.get("tags", {}).get("tags", [])]

        return {
            "source": "intercom",
            "source_id": str(conv.get("id")),
            "title": source.get("subject") or clean_body[:100],
            "text": clean_body,
            "author": source.get("author", {}).get("email"),
            "rating": rating.get("rating") if rating else None,
            "metadata": {
                "state": conv.get("state"),
                "tags": tags,
                "rating_remark": rating.get("remark") if rating else None,
                "source_type": source.get("type"),
            },
            "source_created_at": datetime.fromtimestamp(
                conv.get("created_at", 0), tz=timezone.utc
            ).isoformat()
            if conv.get("created_at")
            else None,
        }

    def _normalize_part(self, conv: dict, part: dict) -> dict | None:
        body = part.get("body") or ""
        if not body.strip():
            return None

        import re
        clean_body = re.sub(r"<[^>]+>", " ", body)
        clean_body = re.sub(r"\s+", " ", clean_body).strip()

        return {
            "source": "intercom",
            "source_id": f"{conv.get('id')}_part_{part.get('id')}",
            "title": None,
            "text": clean_body,
            "author": part.get("author", {}).get("email"),
            "metadata": {
                "conversation_id": conv.get("id"),
                "part_type": part.get("part_type"),
            },
            "source_created_at": datetime.fromtimestamp(
                part.get("created_at", 0), tz=timezone.utc
            ).isoformat()
            if part.get("created_at")
            else None,
        }
