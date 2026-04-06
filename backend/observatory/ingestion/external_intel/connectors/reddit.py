"""Reddit social listening connector — monitors subreddits for competitor and product mentions."""

import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from observatory.ingestion.base import BaseConnector, ConnectionStatus, SyncResult

logger = structlog.get_logger()


class RedditConnector(BaseConnector):
    """
    Monitors Reddit for mentions of the company, competitors, and relevant topics.

    Required credentials:
        - client_id: str (Reddit API app client ID)
        - client_secret: str
        - user_agent: str

    Config options:
        - subreddits: list[str] — subreddits to monitor
        - search_terms: list[str] — keywords to search across Reddit
        - competitor_names: list[str] — competitor names to track mentions
        - max_posts: int — max posts per subreddit per sync (default: 100)
    """

    AUTH_URL = "https://www.reddit.com/api/v1/access_token"
    BASE_URL = "https://oauth.reddit.com"

    def __init__(self, org_id: uuid.UUID, credentials: dict[str, Any], config: dict[str, Any]):
        super().__init__(org_id, credentials, config)
        self.client_id = credentials["client_id"]
        self.client_secret = credentials["client_secret"]
        self.user_agent = credentials.get("user_agent", "Observatory/1.0")
        self.subreddits = config.get("subreddits", [])
        self.search_terms = config.get("search_terms", [])
        self.competitor_names = config.get("competitor_names", [])
        self.max_posts = config.get("max_posts", 100)
        self._access_token: str | None = None

    async def authenticate(self) -> ConnectionStatus:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self.AUTH_URL,
                    data={"grant_type": "client_credentials"},
                    auth=(self.client_id, self.client_secret),
                    headers={"User-Agent": self.user_agent},
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                self._access_token = data["access_token"]
                return ConnectionStatus(connected=True, message="Authenticated with Reddit API")
        except Exception as e:
            return ConnectionStatus(connected=False, message=str(e))

    async def test_connection(self) -> bool:
        return (await self.authenticate()).connected

    async def get_schema(self) -> dict[str, Any]:
        return {
            "source": "reddit",
            "data_types": ["posts", "comments"],
            "fields": {
                "post": ["id", "subreddit", "title", "text", "author", "score", "url", "created_utc"],
            },
        }

    async def sync(self, since: datetime | None = None) -> SyncResult:
        result = SyncResult()
        if not self._access_token:
            auth = await self.authenticate()
            if not auth.connected:
                result.errors.append("Authentication failed")
                return result

        mentions: list[dict] = []

        # Monitor subreddits
        for subreddit in self.subreddits:
            posts = await self._fetch_subreddit_posts(subreddit, since)
            mentions.extend(posts)

        # Search for specific terms
        for term in self.search_terms:
            posts = await self._search_reddit(term, since)
            mentions.extend(posts)

        # Deduplicate by source_id
        seen = set()
        unique_mentions = []
        for m in mentions:
            if m["source_id"] not in seen:
                seen.add(m["source_id"])
                unique_mentions.append(m)

        # Tag which competitor each mention references
        for mention in unique_mentions:
            text = f"{mention.get('title', '')} {mention.get('text', '')}".lower()
            for comp in self.competitor_names:
                if comp.lower() in text:
                    mention["mentions_competitor"] = comp
                    break

        result.records_fetched = len(unique_mentions)
        result.records_created = len(unique_mentions)
        result.completed_at = datetime.now(timezone.utc)
        result._records = unique_mentions  # type: ignore[attr-defined]

        logger.info(
            "reddit_sync_complete",
            org_id=str(self.org_id),
            mentions=len(unique_mentions),
        )
        return result

    async def _fetch_subreddit_posts(
        self, subreddit: str, since: datetime | None
    ) -> list[dict]:
        posts = []
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.BASE_URL}/r/{subreddit}/new.json",
                    params={"limit": self.max_posts},
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "User-Agent": self.user_agent,
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()

                for child in data.get("data", {}).get("children", []):
                    post = child.get("data", {})
                    created = datetime.fromtimestamp(post.get("created_utc", 0), tz=timezone.utc)
                    if since and created < since:
                        continue

                    posts.append(self._normalize_post(post, subreddit))
        except Exception as e:
            logger.error("reddit_subreddit_error", subreddit=subreddit, error=str(e))

        return posts

    async def _search_reddit(self, query: str, since: datetime | None) -> list[dict]:
        posts = []
        try:
            async with httpx.AsyncClient() as client:
                params: dict[str, Any] = {
                    "q": query,
                    "sort": "new",
                    "limit": self.max_posts,
                    "type": "link",
                }
                if since:
                    # Reddit search doesn't have exact timestamp filters,
                    # use time restriction
                    params["t"] = "week"

                resp = await client.get(
                    f"{self.BASE_URL}/search.json",
                    params=params,
                    headers={
                        "Authorization": f"Bearer {self._access_token}",
                        "User-Agent": self.user_agent,
                    },
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()

                for child in data.get("data", {}).get("children", []):
                    post = child.get("data", {})
                    posts.append(self._normalize_post(post, post.get("subreddit", "")))
        except Exception as e:
            logger.error("reddit_search_error", query=query, error=str(e))

        return posts

    def _normalize_post(self, post: dict, subreddit: str) -> dict:
        return {
            "platform": "reddit",
            "source_id": post.get("id", ""),
            "source_url": f"https://reddit.com{post.get('permalink', '')}",
            "author": post.get("author"),
            "text": f"{post.get('title', '')}\n\n{post.get('selftext', '')}".strip(),
            "topics": [subreddit],
            "engagement_score": post.get("score", 0),
            "posted_at": datetime.fromtimestamp(
                post.get("created_utc", 0), tz=timezone.utc
            ).isoformat(),
            "metadata": {
                "subreddit": subreddit,
                "num_comments": post.get("num_comments", 0),
                "upvote_ratio": post.get("upvote_ratio", 0),
                "is_self": post.get("is_self", True),
                "flair": post.get("link_flair_text"),
            },
        }
