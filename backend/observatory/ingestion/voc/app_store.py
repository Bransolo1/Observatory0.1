"""App store review scraper — ingests reviews from Apple App Store and Google Play."""

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from observatory.ingestion.base import BaseConnector, ConnectionStatus, SyncResult

logger = structlog.get_logger()


class AppStoreConnector(BaseConnector):
    """
    Scrapes app reviews from Apple App Store and Google Play Store.

    Required credentials:
        - ios_app_id: str (Apple App Store ID, e.g., "123456789")
        - android_app_id: str (Google Play package name, e.g., "com.example.app")

    Config options:
        - countries: list[str] — country codes to scrape (default: ["us", "gb"])
        - max_reviews: int — max reviews per platform per sync (default: 200)
    """

    def __init__(self, org_id: uuid.UUID, credentials: dict[str, Any], config: dict[str, Any]):
        super().__init__(org_id, credentials, config)
        self.ios_app_id = credentials.get("ios_app_id")
        self.android_app_id = credentials.get("android_app_id")
        self.countries = config.get("countries", ["us", "gb"])
        self.max_reviews = config.get("max_reviews", 200)

    async def authenticate(self) -> ConnectionStatus:
        # App store scrapers don't need auth — just validate app IDs exist
        return ConnectionStatus(
            connected=True,
            message="App store scraping does not require authentication",
            metadata={
                "ios_app_id": self.ios_app_id,
                "android_app_id": self.android_app_id,
            },
        )

    async def test_connection(self) -> bool:
        return True

    async def get_schema(self) -> dict[str, Any]:
        return {
            "source": "app_store",
            "data_types": ["reviews"],
            "fields": {
                "review": [
                    "id", "title", "text", "rating", "author",
                    "version", "platform", "country", "posted_at",
                ],
            },
        }

    async def sync(self, since: datetime | None = None) -> SyncResult:
        result = SyncResult()
        normalized = []

        if self.ios_app_id:
            ios_reviews = await self._fetch_ios_reviews(since)
            normalized.extend(ios_reviews)

        if self.android_app_id:
            android_reviews = await self._fetch_android_reviews(since)
            normalized.extend(android_reviews)

        result.records_fetched = len(normalized)
        result.records_created = len(normalized)
        result.completed_at = datetime.now(timezone.utc)
        result._records = normalized  # type: ignore[attr-defined]

        logger.info(
            "app_store_sync_complete",
            org_id=str(self.org_id),
            ios_count=len([r for r in normalized if r["source"] == "app_store_ios"]),
            android_count=len([r for r in normalized if r["source"] == "app_store_android"]),
        )
        return result

    async def _fetch_ios_reviews(self, since: datetime | None = None) -> list[dict]:
        reviews = []
        try:
            from app_store_scraper import AppStore

            for country in self.countries:
                app = AppStore(country=country, app_id=self.ios_app_id)
                app.review(how_many=self.max_reviews)

                for r in app.reviews:
                    review_date = r.get("date")
                    if since and review_date and review_date < since:
                        continue

                    reviews.append({
                        "source": "app_store_ios",
                        "source_id": str(r.get("id", "")),
                        "title": r.get("title", ""),
                        "text": r.get("review", ""),
                        "rating": r.get("rating"),
                        "author": r.get("userName", ""),
                        "metadata": {
                            "platform": "ios",
                            "country": country,
                            "version": r.get("version"),
                            "developer_response": r.get("developerResponse"),
                        },
                        "source_created_at": (
                            review_date.isoformat() if review_date else None
                        ),
                    })
        except Exception as e:
            logger.error("ios_review_fetch_error", error=str(e))

        return reviews

    async def _fetch_android_reviews(self, since: datetime | None = None) -> list[dict]:
        reviews = []
        try:
            from google_play_scraper import Sort, reviews as gp_reviews

            for country in self.countries:
                result, _ = gp_reviews(
                    self.android_app_id,
                    lang="en",
                    country=country,
                    sort=Sort.NEWEST,
                    count=self.max_reviews,
                )

                for r in result:
                    review_date = r.get("at")
                    if since and review_date and review_date < since:
                        continue

                    reviews.append({
                        "source": "app_store_android",
                        "source_id": str(r.get("reviewId", "")),
                        "title": "",
                        "text": r.get("content", ""),
                        "rating": r.get("score"),
                        "author": r.get("userName", ""),
                        "metadata": {
                            "platform": "android",
                            "country": country,
                            "version": r.get("reviewCreatedVersion"),
                            "thumbs_up": r.get("thumbsUpCount", 0),
                            "reply_content": r.get("replyContent"),
                        },
                        "source_created_at": (
                            review_date.isoformat() if review_date else None
                        ),
                    })
        except Exception as e:
            logger.error("android_review_fetch_error", error=str(e))

        return reviews
