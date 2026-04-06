"""Week-over-week competitive change detection engine."""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from observatory.core.llm import get_llm_service
from observatory.core.models.competitor import (
    CompetitorChange,
    CompetitorProfile,
    CompetitorReview,
    SocialMention,
)

logger = structlog.get_logger()


class CompetitiveChangeDetector:
    """Detects week-over-week changes in competitive landscape."""

    def __init__(self, db: AsyncSession, org_id: uuid.UUID):
        self.db = db
        self.org_id = org_id
        self.llm = get_llm_service()

    async def detect_changes(self) -> dict[str, Any]:
        """Run full week-over-week competitive change detection."""
        now = datetime.now(timezone.utc)
        this_week_start = now - timedelta(days=7)
        last_week_start = now - timedelta(days=14)

        competitors = await self._get_active_competitors()

        report = {
            "org_id": str(self.org_id),
            "period": {
                "this_week": {"start": this_week_start.isoformat(), "end": now.isoformat()},
                "last_week": {"start": last_week_start.isoformat(), "end": this_week_start.isoformat()},
            },
            "competitors": [],
            "summary": "",
            "alerts": [],
        }

        for comp in competitors:
            comp_report = await self._analyze_competitor(
                comp, this_week_start, last_week_start, now
            )
            report["competitors"].append(comp_report)

            # Generate alerts for significant changes
            for alert in comp_report.get("alerts", []):
                report["alerts"].append(alert)

        # Generate overall summary via LLM
        if report["competitors"]:
            report["summary"] = await self._generate_summary(report)

        logger.info(
            "competitive_change_detection_complete",
            org_id=str(self.org_id),
            competitors_analyzed=len(competitors),
            alerts=len(report["alerts"]),
        )
        return report

    async def _get_active_competitors(self) -> list:
        result = await self.db.execute(
            select(CompetitorProfile).where(
                CompetitorProfile.org_id == self.org_id,
                CompetitorProfile.is_active.is_(True),
            )
        )
        return result.scalars().all()

    async def _analyze_competitor(
        self,
        competitor: CompetitorProfile,
        this_week_start: datetime,
        last_week_start: datetime,
        now: datetime,
    ) -> dict[str, Any]:
        comp_id = competitor.id

        # Count changes this week vs last week
        this_week_changes = await self._count_changes(comp_id, this_week_start, now)
        last_week_changes = await self._count_changes(comp_id, last_week_start, this_week_start)

        # Get change details
        recent_changes = await self._get_recent_changes(comp_id, this_week_start)

        # Review sentiment analysis
        this_week_reviews = await self._get_review_stats(comp_id, this_week_start, now)
        last_week_reviews = await self._get_review_stats(comp_id, last_week_start, this_week_start)

        # Social mention volume
        this_week_mentions = await self._count_mentions(comp_id, this_week_start, now)
        last_week_mentions = await self._count_mentions(comp_id, last_week_start, this_week_start)

        alerts = []

        # Alert: significant change detected
        high_sig_changes = [c for c in recent_changes if c.significance in ("high", "critical")]
        if high_sig_changes:
            alerts.append({
                "type": "significant_change",
                "competitor": competitor.name,
                "severity": "high",
                "message": f"{competitor.name} has {len(high_sig_changes)} significant changes this week",
                "details": [{"title": c.title, "type": c.change_type} for c in high_sig_changes],
            })

        # Alert: review sentiment drop
        if this_week_reviews["avg_rating"] and last_week_reviews["avg_rating"]:
            rating_delta = this_week_reviews["avg_rating"] - last_week_reviews["avg_rating"]
            if abs(rating_delta) >= 0.5:
                alerts.append({
                    "type": "review_sentiment_shift",
                    "competitor": competitor.name,
                    "severity": "medium",
                    "message": f"{competitor.name} review rating {'increased' if rating_delta > 0 else 'decreased'} by {abs(rating_delta):.1f}",
                    "details": {
                        "this_week": this_week_reviews["avg_rating"],
                        "last_week": last_week_reviews["avg_rating"],
                        "delta": rating_delta,
                    },
                })

        # Alert: social mention spike (>2x volume)
        if last_week_mentions > 0 and this_week_mentions > last_week_mentions * 2:
            alerts.append({
                "type": "mention_spike",
                "competitor": competitor.name,
                "severity": "medium",
                "message": f"{competitor.name} social mentions spiked {this_week_mentions/last_week_mentions:.1f}x",
                "details": {
                    "this_week": this_week_mentions,
                    "last_week": last_week_mentions,
                },
            })

        return {
            "competitor_id": str(comp_id),
            "competitor_name": competitor.name,
            "changes": {
                "this_week": this_week_changes,
                "last_week": last_week_changes,
                "delta": this_week_changes - last_week_changes,
                "recent": [
                    {
                        "title": c.title,
                        "type": c.change_type,
                        "significance": c.significance,
                        "detected_at": c.detected_at.isoformat() if c.detected_at else None,
                    }
                    for c in recent_changes[:10]
                ],
            },
            "reviews": {
                "this_week": this_week_reviews,
                "last_week": last_week_reviews,
                "rating_delta": (
                    (this_week_reviews["avg_rating"] or 0) - (last_week_reviews["avg_rating"] or 0)
                    if this_week_reviews["avg_rating"] and last_week_reviews["avg_rating"]
                    else None
                ),
            },
            "social_mentions": {
                "this_week": this_week_mentions,
                "last_week": last_week_mentions,
                "change_pct": (
                    ((this_week_mentions - last_week_mentions) / last_week_mentions * 100)
                    if last_week_mentions > 0
                    else None
                ),
            },
            "alerts": alerts,
        }

    async def _count_changes(
        self, competitor_id: uuid.UUID, start: datetime, end: datetime
    ) -> int:
        result = await self.db.execute(
            select(func.count(CompetitorChange.id)).where(
                CompetitorChange.competitor_id == competitor_id,
                CompetitorChange.detected_at >= start,
                CompetitorChange.detected_at < end,
            )
        )
        return result.scalar() or 0

    async def _get_recent_changes(
        self, competitor_id: uuid.UUID, since: datetime
    ) -> list:
        result = await self.db.execute(
            select(CompetitorChange)
            .where(
                CompetitorChange.competitor_id == competitor_id,
                CompetitorChange.detected_at >= since,
            )
            .order_by(CompetitorChange.detected_at.desc())
        )
        return result.scalars().all()

    async def _get_review_stats(
        self, competitor_id: uuid.UUID, start: datetime, end: datetime
    ) -> dict[str, Any]:
        result = await self.db.execute(
            select(
                func.count(CompetitorReview.id),
                func.avg(CompetitorReview.rating),
            ).where(
                CompetitorReview.competitor_id == competitor_id,
                CompetitorReview.created_at >= start,
                CompetitorReview.created_at < end,
            )
        )
        row = result.one()
        return {
            "count": row[0] or 0,
            "avg_rating": round(float(row[1]), 2) if row[1] else None,
        }

    async def _count_mentions(
        self, competitor_id: uuid.UUID, start: datetime, end: datetime
    ) -> int:
        # SocialMention uses mentions_competitor (competitor name string), not ID
        # So we count by org_id within the time range
        result = await self.db.execute(
            select(func.count(SocialMention.id)).where(
                SocialMention.org_id == self.org_id,
                SocialMention.posted_at >= start,
                SocialMention.posted_at < end,
            )
        )
        return result.scalar() or 0

    async def _generate_summary(self, report: dict) -> str:
        context = []
        for comp in report["competitors"]:
            context.append(
                f"Competitor: {comp['competitor_name']}\n"
                f"  Changes this week: {comp['changes']['this_week']} (last week: {comp['changes']['last_week']})\n"
                f"  Review rating: {comp['reviews']['this_week'].get('avg_rating', 'N/A')}\n"
                f"  Social mentions: {comp['social_mentions']['this_week']} (last week: {comp['social_mentions']['last_week']})\n"
                f"  Alerts: {len(comp['alerts'])}"
            )

        prompt = (
            "Summarize the following week-over-week competitive intelligence report in 3-5 sentences. "
            "Highlight the most important changes, trends, and anything that requires immediate attention.\n\n"
            + "\n\n".join(context)
        )

        try:
            response = await self.llm.complete(prompt=prompt, tier="DEFAULT")
            return response
        except Exception as e:
            logger.error("competitive_summary_error", error=str(e))
            return f"Summary generation failed: {str(e)}"
