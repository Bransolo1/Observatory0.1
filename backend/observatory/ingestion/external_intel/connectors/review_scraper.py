"""Review aggregation scraper — collects competitor reviews from G2, Trustpilot, Capterra."""

import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from observatory.ingestion.base import BaseConnector, ConnectionStatus, SyncResult

logger = structlog.get_logger()


class ReviewScraperConnector(BaseConnector):
    """
    Scrapes competitor reviews from review platforms.

    Required credentials: (none for public scraping, API key for G2 if available)
        - g2_api_token: str | None

    Config options:
        - competitors: list[dict] — each with:
            - name: str
            - competitor_id: str (Observatory competitor UUID)
            - g2_slug: str | None (e.g., "slack")
            - trustpilot_domain: str | None (e.g., "slack.com")
            - capterra_slug: str | None
        - max_reviews_per_source: int (default: 50)
    """

    G2_BASE = "https://www.g2.com/products"
    TRUSTPILOT_API = "https://www.trustpilot.com/api/categories-pages"

    def __init__(self, org_id: uuid.UUID, credentials: dict[str, Any], config: dict[str, Any]):
        super().__init__(org_id, credentials, config)
        self.g2_api_token = credentials.get("g2_api_token")
        self.competitors_config = config.get("competitors", [])
        self.max_reviews = config.get("max_reviews_per_source", 50)

    async def authenticate(self) -> ConnectionStatus:
        return ConnectionStatus(connected=True, message="Review scraping configured")

    async def test_connection(self) -> bool:
        return True

    async def get_schema(self) -> dict[str, Any]:
        return {
            "source": "review_scraper",
            "data_types": ["reviews"],
            "platforms": ["g2", "trustpilot", "capterra"],
            "fields": {
                "review": [
                    "platform", "competitor_id", "source_id", "author",
                    "rating", "title", "text", "posted_at",
                ],
            },
        }

    async def sync(self, since: datetime | None = None) -> SyncResult:
        result = SyncResult()
        all_reviews: list[dict] = []

        for comp in self.competitors_config:
            competitor_id = comp["competitor_id"]
            name = comp["name"]

            # G2 reviews
            if comp.get("g2_slug"):
                g2_reviews = await self._fetch_g2_reviews(comp["g2_slug"], competitor_id, since)
                all_reviews.extend(g2_reviews)

            # Trustpilot reviews
            if comp.get("trustpilot_domain"):
                tp_reviews = await self._fetch_trustpilot_reviews(
                    comp["trustpilot_domain"], competitor_id, since
                )
                all_reviews.extend(tp_reviews)

            logger.info(
                "review_scraper_competitor_done",
                competitor=name,
                reviews=len([r for r in all_reviews if r.get("competitor_id") == competitor_id]),
            )

        result.records_fetched = len(all_reviews)
        result.records_created = len(all_reviews)
        result.completed_at = datetime.now(timezone.utc)
        result._records = all_reviews  # type: ignore[attr-defined]

        logger.info(
            "review_scraper_sync_complete",
            org_id=str(self.org_id),
            total_reviews=len(all_reviews),
        )
        return result

    async def _fetch_g2_reviews(
        self, slug: str, competitor_id: str, since: datetime | None
    ) -> list[dict]:
        """Fetch reviews from G2 via scraping or API."""
        reviews = []
        try:
            async with httpx.AsyncClient() as client:
                # G2 public reviews page scraping
                resp = await client.get(
                    f"{self.G2_BASE}/{slug}/reviews",
                    headers={
                        "User-Agent": "Mozilla/5.0 (compatible; Observatory/1.0)",
                        "Accept": "text/html",
                    },
                    timeout=20,
                    follow_redirects=True,
                )
                if resp.status_code == 200:
                    # Parse review data from page
                    reviews.extend(
                        self._parse_g2_html(resp.text, slug, competitor_id)
                    )
        except Exception as e:
            logger.error("g2_fetch_error", slug=slug, error=str(e))

        return reviews[:self.max_reviews]

    async def _fetch_trustpilot_reviews(
        self, domain: str, competitor_id: str, since: datetime | None
    ) -> list[dict]:
        """Fetch reviews from Trustpilot public API."""
        reviews = []
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"https://www.trustpilot.com/review/{domain}",
                    headers={
                        "User-Agent": "Mozilla/5.0 (compatible; Observatory/1.0)",
                        "Accept": "text/html",
                    },
                    timeout=20,
                    follow_redirects=True,
                )
                if resp.status_code == 200:
                    reviews.extend(
                        self._parse_trustpilot_html(resp.text, domain, competitor_id)
                    )
        except Exception as e:
            logger.error("trustpilot_fetch_error", domain=domain, error=str(e))

        return reviews[:self.max_reviews]

    def _parse_g2_html(self, html: str, slug: str, competitor_id: str) -> list[dict]:
        """Extract reviews from G2 HTML. Basic extraction — production would use structured parsing."""
        import re

        reviews = []
        # Look for JSON-LD review data
        ld_matches = re.findall(r'"reviewRating":\s*\{[^}]*"ratingValue":\s*"?(\d)"?', html)
        text_matches = re.findall(
            r'<div[^>]*itemprop="reviewBody"[^>]*>(.*?)</div>', html, re.DOTALL
        )

        for i, text in enumerate(text_matches[:self.max_reviews]):
            clean_text = re.sub(r"<[^>]+>", " ", text).strip()
            if len(clean_text) < 10:
                continue
            rating = int(ld_matches[i]) if i < len(ld_matches) else None
            reviews.append({
                "platform": "g2",
                "competitor_id": competitor_id,
                "source_id": f"g2_{slug}_{i}",
                "author": None,
                "rating": rating,
                "title": None,
                "text": clean_text[:2000],
                "posted_at": datetime.now(timezone.utc).isoformat(),
            })

        return reviews

    def _parse_trustpilot_html(
        self, html: str, domain: str, competitor_id: str
    ) -> list[dict]:
        """Extract reviews from Trustpilot HTML."""
        import re

        reviews = []
        # Look for review cards
        review_blocks = re.findall(
            r'data-review-id="([^"]*)".*?data-service-review-rating="(\d)".*?'
            r'<p[^>]*data-service-review-text[^>]*>(.*?)</p>',
            html,
            re.DOTALL,
        )

        for review_id, rating, text in review_blocks[:self.max_reviews]:
            clean_text = re.sub(r"<[^>]+>", " ", text).strip()
            if len(clean_text) < 10:
                continue
            reviews.append({
                "platform": "trustpilot",
                "competitor_id": competitor_id,
                "source_id": f"tp_{review_id}",
                "author": None,
                "rating": int(rating),
                "title": None,
                "text": clean_text[:2000],
                "posted_at": datetime.now(timezone.utc).isoformat(),
            })

        return reviews
