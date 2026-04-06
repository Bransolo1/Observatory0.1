"""Zendesk connector — ingests support tickets as VoC feedback."""

import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from observatory.ingestion.base import BaseConnector, ConnectionStatus, SyncResult

logger = structlog.get_logger()


class ZendeskConnector(BaseConnector):
    """
    Connects to Zendesk Support API to pull tickets, comments, and satisfaction data.

    Required credentials:
        - subdomain: str (e.g., "mycompany")
        - email: str (agent email)
        - api_token: str

    Config options:
        - ticket_status: list[str] — filter by status (default: all)
        - include_comments: bool — fetch ticket comments (default: True)
        - tags_filter: list[str] — only sync tickets with these tags (optional)
    """

    BASE_URL = "https://{subdomain}.zendesk.com/api/v2"

    def __init__(self, org_id: uuid.UUID, credentials: dict[str, Any], config: dict[str, Any]):
        super().__init__(org_id, credentials, config)
        self.subdomain = credentials["subdomain"]
        self.auth = (f"{credentials['email']}/token", credentials["api_token"])
        self.base_url = self.BASE_URL.format(subdomain=self.subdomain)
        self.include_comments = config.get("include_comments", True)

    async def authenticate(self) -> ConnectionStatus:
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{self.base_url}/users/me.json",
                    auth=self.auth,
                    timeout=10.0,
                )
                if response.status_code == 200:
                    user = response.json()["user"]
                    return ConnectionStatus(
                        connected=True,
                        message=f"Authenticated as {user['name']}",
                        metadata={"user_id": user["id"], "role": user.get("role")},
                    )
                return ConnectionStatus(connected=False, message=f"HTTP {response.status_code}")
            except httpx.HTTPError as e:
                return ConnectionStatus(connected=False, message=str(e))

    async def test_connection(self) -> bool:
        status = await self.authenticate()
        return status.connected

    async def get_schema(self) -> dict[str, Any]:
        return {
            "source": "zendesk",
            "data_types": ["tickets", "comments", "satisfaction_ratings"],
            "fields": {
                "ticket": ["id", "subject", "description", "status", "priority", "tags", "created_at"],
                "comment": ["id", "body", "author_id", "created_at"],
            },
        }

    async def sync(self, since: datetime | None = None) -> SyncResult:
        result = SyncResult()
        logger.info("zendesk_sync_start", org_id=str(self.org_id), since=since)

        try:
            tickets = await self._fetch_tickets(since)
            result.records_fetched = len(tickets)

            normalized = []
            for ticket in tickets:
                feedback = self._normalize_ticket(ticket)
                normalized.append(feedback)

                if self.include_comments:
                    comments = await self._fetch_comments(ticket["id"])
                    for comment in comments:
                        feedback_comment = self._normalize_comment(ticket, comment)
                        normalized.append(feedback_comment)

            result.records_created = len(normalized)
            result.completed_at = datetime.now(timezone.utc)

            logger.info(
                "zendesk_sync_complete",
                org_id=str(self.org_id),
                fetched=result.records_fetched,
                created=result.records_created,
            )

            # Return normalized records for the pipeline to persist
            result._records = normalized  # type: ignore[attr-defined]

        except Exception as e:
            logger.error("zendesk_sync_error", error=str(e))
            result.errors.append(str(e))

        return result

    async def _fetch_tickets(self, since: datetime | None = None) -> list[dict]:
        tickets = []
        url = f"{self.base_url}/incremental/tickets.json"
        params: dict[str, Any] = {}
        if since:
            params["start_time"] = int(since.timestamp())
        else:
            # Default to last 30 days
            params["start_time"] = int(
                (datetime.now(timezone.utc).timestamp()) - (30 * 86400)
            )

        async with httpx.AsyncClient() as client:
            while url:
                response = await client.get(
                    url, auth=self.auth, params=params, timeout=30.0
                )
                response.raise_for_status()
                data = response.json()
                tickets.extend(data.get("tickets", []))

                if data.get("end_of_stream"):
                    break
                url = data.get("next_page")
                params = {}  # next_page URL includes params

        return tickets

    async def _fetch_comments(self, ticket_id: int) -> list[dict]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/tickets/{ticket_id}/comments.json",
                auth=self.auth,
                timeout=15.0,
            )
            response.raise_for_status()
            return response.json().get("comments", [])

    def _normalize_ticket(self, ticket: dict) -> dict:
        return {
            "source": "zendesk",
            "source_id": str(ticket["id"]),
            "source_url": ticket.get("url"),
            "title": ticket.get("subject"),
            "text": ticket.get("description", ""),
            "author": ticket.get("requester_id"),
            "metadata": {
                "status": ticket.get("status"),
                "priority": ticket.get("priority"),
                "tags": ticket.get("tags", []),
                "ticket_type": ticket.get("type"),
                "satisfaction_rating": ticket.get("satisfaction_rating"),
            },
            "source_created_at": ticket.get("created_at"),
        }

    def _normalize_comment(self, ticket: dict, comment: dict) -> dict:
        return {
            "source": "zendesk",
            "source_id": f"{ticket['id']}_comment_{comment['id']}",
            "source_url": ticket.get("url"),
            "title": ticket.get("subject"),
            "text": comment.get("body", ""),
            "author": str(comment.get("author_id")),
            "metadata": {
                "ticket_id": ticket["id"],
                "comment_id": comment["id"],
                "public": comment.get("public", True),
            },
            "source_created_at": comment.get("created_at"),
        }
