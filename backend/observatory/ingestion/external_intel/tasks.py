"""Celery tasks for external intelligence ingestion."""

import asyncio
from datetime import datetime, timezone

import structlog

from observatory.core.tasks import app

logger = structlog.get_logger()


@app.task(name="observatory.ingestion.external_intel.tasks.scan_all_competitors")
def scan_all_competitors():
    """Weekly competitor scan across all orgs — website changes, social, reviews."""
    asyncio.run(_scan_all())


@app.task(name="observatory.ingestion.external_intel.tasks.scan_social_mentions")
def scan_social_mentions():
    """Scan Reddit and HN for mentions (runs every 6 hours)."""
    asyncio.run(_scan_social())


async def _scan_all():
    from sqlalchemy import select

    from observatory.core.database import async_session_factory
    from observatory.core.llm import get_llm_service
    from observatory.core.models.competitor import (
        CompetitorChange,
        CompetitorProfile,
        CompetitorReview,
        SocialMention,
    )
    from observatory.core.models.organization import Organization
    from observatory.ingestion.external_intel.connectors.website_monitor import (
        WebsiteMonitorConnector,
    )
    from observatory.ingestion.external_intel.connectors.review_scraper import (
        ReviewScraperConnector,
    )

    llm = get_llm_service()

    async with async_session_factory() as db:
        result = await db.execute(
            select(Organization).where(Organization.is_active.is_(True))
        )
        orgs = result.scalars().all()

        for org in orgs:
            try:
                # Get org's competitors
                comp_result = await db.execute(
                    select(CompetitorProfile).where(
                        CompetitorProfile.org_id == org.id,
                        CompetitorProfile.is_active.is_(True),
                    )
                )
                competitors = comp_result.scalars().all()

                # Website monitoring
                for comp in competitors:
                    tracking = comp.tracking_config or {}
                    urls = tracking.get("monitor_urls", [])
                    if urls:
                        monitor = WebsiteMonitorConnector(
                            org_id=org.id,
                            credentials={},
                            config={"urls": urls},
                            llm=llm,
                        )
                        sync_result = await monitor.sync()
                        for change_data in getattr(sync_result, "_records", []):
                            change = CompetitorChange(
                                org_id=org.id,
                                competitor_id=comp.id,
                                change_type=change_data.get("change_type", "other"),
                                title=change_data.get("title", "Unknown change"),
                                description=change_data.get("description", ""),
                                significance=change_data.get("significance", "low"),
                                source_url=change_data.get("source_url"),
                                evidence=change_data,
                                detected_at=datetime.now(timezone.utc),
                            )
                            db.add(change)

                # Review scraping
                review_config = []
                for comp in competitors:
                    tracking = comp.tracking_config or {}
                    if tracking.get("g2_slug") or tracking.get("trustpilot_domain"):
                        review_config.append({
                            "name": comp.name,
                            "competitor_id": str(comp.id),
                            "g2_slug": tracking.get("g2_slug"),
                            "trustpilot_domain": tracking.get("trustpilot_domain"),
                        })

                if review_config:
                    scraper = ReviewScraperConnector(
                        org_id=org.id,
                        credentials={},
                        config={"competitors": review_config},
                    )
                    sync_result = await scraper.sync()
                    for review_data in getattr(sync_result, "_records", []):
                        review = CompetitorReview(
                            org_id=org.id,
                            competitor_id=review_data["competitor_id"],
                            platform=review_data["platform"],
                            source_id=review_data["source_id"],
                            author=review_data.get("author"),
                            rating=review_data.get("rating"),
                            title=review_data.get("title"),
                            text=review_data["text"],
                            posted_at=datetime.fromisoformat(review_data["posted_at"]),
                        )
                        db.add(review)

                await db.commit()
                logger.info("org_competitor_scan_done", org_id=str(org.id))

            except Exception as e:
                logger.error("org_competitor_scan_error", org_id=str(org.id), error=str(e))


async def _scan_social():
    from sqlalchemy import select

    from observatory.core.database import async_session_factory
    from observatory.core.models.competitor import CompetitorProfile, SocialMention
    from observatory.core.models.organization import Organization
    from observatory.ingestion.external_intel.connectors.reddit import RedditConnector
    from observatory.ingestion.external_intel.connectors.hackernews import HackerNewsConnector

    async with async_session_factory() as db:
        result = await db.execute(
            select(Organization).where(Organization.is_active.is_(True))
        )
        orgs = result.scalars().all()

        for org in orgs:
            try:
                org_settings = org.settings or {}
                social_config = org_settings.get("social_listening", {})

                comp_result = await db.execute(
                    select(CompetitorProfile.name).where(
                        CompetitorProfile.org_id == org.id,
                        CompetitorProfile.is_active.is_(True),
                    )
                )
                competitor_names = [row[0] for row in comp_result.all()]

                # Reddit
                reddit_creds = social_config.get("reddit", {})
                if reddit_creds.get("client_id"):
                    reddit = RedditConnector(
                        org_id=org.id,
                        credentials=reddit_creds,
                        config={
                            "subreddits": social_config.get("subreddits", []),
                            "search_terms": social_config.get("search_terms", []),
                            "competitor_names": competitor_names,
                        },
                    )
                    sync_result = await reddit.sync()
                    for mention_data in getattr(sync_result, "_records", []):
                        mention = SocialMention(
                            org_id=org.id,
                            platform=mention_data["platform"],
                            source_id=mention_data["source_id"],
                            source_url=mention_data.get("source_url"),
                            author=mention_data.get("author"),
                            text=mention_data["text"],
                            topics=mention_data.get("topics", []),
                            mentions_competitor=mention_data.get("mentions_competitor"),
                            engagement_score=mention_data.get("engagement_score", 0),
                            posted_at=datetime.fromisoformat(mention_data["posted_at"]),
                        )
                        db.add(mention)

                # Hacker News (no auth needed)
                hn_terms = social_config.get("search_terms", []) + competitor_names
                if hn_terms:
                    hn = HackerNewsConnector(
                        org_id=org.id,
                        credentials={},
                        config={
                            "search_terms": hn_terms,
                            "competitor_names": competitor_names,
                        },
                    )
                    sync_result = await hn.sync()
                    for mention_data in getattr(sync_result, "_records", []):
                        mention = SocialMention(
                            org_id=org.id,
                            platform=mention_data["platform"],
                            source_id=mention_data["source_id"],
                            source_url=mention_data.get("source_url"),
                            author=mention_data.get("author"),
                            text=mention_data["text"],
                            topics=mention_data.get("topics", []),
                            mentions_competitor=mention_data.get("mentions_competitor"),
                            engagement_score=mention_data.get("engagement_score", 0),
                            posted_at=datetime.fromisoformat(mention_data["posted_at"]),
                        )
                        db.add(mention)

                await db.commit()
                logger.info("org_social_scan_done", org_id=str(org.id))

            except Exception as e:
                logger.error("org_social_scan_error", org_id=str(org.id), error=str(e))
