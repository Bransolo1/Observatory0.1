"""Friction detection engine — correlates telemetry anomalies with VoC signals."""

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from observatory.core.llm.service import LLMService, ModelTier
from observatory.core.models.feedback import Feedback
from observatory.core.models.insight import Insight
from observatory.core.models.telemetry import FrictionSignal, TelemetryAggregate

logger = structlog.get_logger()

FRICTION_SYNTHESIS_SYSTEM = """You are Observatory's friction analysis engine. You identify and explain user friction points by correlating product telemetry data with customer feedback.

Your analysis should:
1. Clearly describe WHAT the friction is (the observable problem)
2. Explain WHY users are struggling (root cause from feedback)
3. Quantify the IMPACT (users affected, severity)
4. Suggest WHAT TO DO about it (actionable recommendation)

Be specific. Reference actual data points. Do not speculate beyond what the evidence supports."""


class FrictionDetector:
    def __init__(self, llm: LLMService, db: AsyncSession):
        self.llm = llm
        self.db = db

    async def detect_anomalies(self, org_id: uuid.UUID) -> list[dict]:
        """Detect statistically significant drop-offs in telemetry data."""
        # Get recent aggregates and compare against baselines
        recent_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        baseline_start = datetime.now(timezone.utc) - timedelta(days=37)
        baseline_end = datetime.now(timezone.utc) - timedelta(days=7)

        # Recent metrics
        recent_result = await self.db.execute(
            select(
                TelemetryAggregate.metric_name,
                TelemetryAggregate.product_area,
                func.avg(TelemetryAggregate.value).label("avg_value"),
                func.count().label("samples"),
            )
            .where(
                TelemetryAggregate.org_id == org_id,
                TelemetryAggregate.metric_type == "funnel_step",
                TelemetryAggregate.metric_date >= recent_cutoff.date(),
            )
            .group_by(TelemetryAggregate.metric_name, TelemetryAggregate.product_area)
        )
        recent_metrics = {row.metric_name: row for row in recent_result.all()}

        # Baseline metrics (30-day window before recent)
        baseline_result = await self.db.execute(
            select(
                TelemetryAggregate.metric_name,
                func.avg(TelemetryAggregate.value).label("avg_value"),
                func.stddev(TelemetryAggregate.value).label("stddev_value"),
            )
            .where(
                TelemetryAggregate.org_id == org_id,
                TelemetryAggregate.metric_type == "funnel_step",
                TelemetryAggregate.metric_date >= baseline_start.date(),
                TelemetryAggregate.metric_date < baseline_end.date(),
            )
            .group_by(TelemetryAggregate.metric_name)
        )
        baseline_metrics = {row.metric_name: row for row in baseline_result.all()}

        anomalies = []
        for metric_name, recent in recent_metrics.items():
            baseline = baseline_metrics.get(metric_name)
            if not baseline or not baseline.stddev_value or baseline.stddev_value == 0:
                continue

            z_score = (recent.avg_value - baseline.avg_value) / baseline.stddev_value

            # Significant negative deviation (drop-off increased)
            if z_score < -2.0:
                severity = "critical" if z_score < -3.0 else "high" if z_score < -2.5 else "medium"
                anomalies.append({
                    "metric_name": metric_name,
                    "product_area": recent.product_area,
                    "current_rate": recent.avg_value,
                    "baseline_rate": baseline.avg_value,
                    "deviation_score": abs(z_score),
                    "severity": severity,
                })

        return anomalies

    async def correlate_with_feedback(
        self, org_id: uuid.UUID, product_area: str
    ) -> list[Feedback]:
        """Find VoC feedback related to a product area."""
        result = await self.db.execute(
            select(Feedback)
            .where(
                Feedback.org_id == org_id,
                Feedback.product_areas.contains([product_area]),
                Feedback.sentiment.in_(["negative", "mixed"]),
            )
            .order_by(Feedback.source_created_at.desc())
            .limit(20)
        )
        return list(result.scalars().all())

    async def generate_friction_report(
        self, org_id: uuid.UUID, anomaly: dict, related_feedback: list[Feedback]
    ) -> Insight:
        """Synthesize a friction report from telemetry anomaly + correlated feedback."""
        feedback_summaries = []
        for f in related_feedback[:10]:
            feedback_summaries.append(
                f"[{f.source}] {f.sentiment} | {f.summary or f.text[:200]}"
            )

        context = [
            f"TELEMETRY ANOMALY:\n"
            f"Metric: {anomaly['metric_name']}\n"
            f"Product Area: {anomaly.get('product_area', 'Unknown')}\n"
            f"Current Rate: {anomaly['current_rate']:.4f}\n"
            f"Baseline Rate: {anomaly['baseline_rate']:.4f}\n"
            f"Deviation: {anomaly['deviation_score']:.2f} standard deviations\n"
            f"Severity: {anomaly['severity']}",
            f"RELATED CUSTOMER FEEDBACK ({len(related_feedback)} items):\n"
            + "\n".join(feedback_summaries),
        ]

        report = await self.llm.synthesize(
            context=context,
            prompt=(
                "Generate a friction report that:\n"
                "1. Titles the friction point concisely\n"
                "2. Explains what is happening (the observable problem)\n"
                "3. Explains why based on customer feedback\n"
                "4. Quantifies the impact\n"
                "5. Recommends a specific action\n\n"
                "Format as:\n"
                "TITLE: ...\n"
                "SUMMARY: (one paragraph)\n"
                "DETAIL: (full analysis)\n"
                "RECOMMENDATION: ..."
            ),
            system=FRICTION_SYNTHESIS_SYSTEM,
        )

        # Parse the LLM output
        lines = report.strip().split("\n")
        title = summary = detail = ""
        current_section = ""
        for line in lines:
            if line.startswith("TITLE:"):
                title = line[6:].strip()
                current_section = "title"
            elif line.startswith("SUMMARY:"):
                summary = line[8:].strip()
                current_section = "summary"
            elif line.startswith("DETAIL:"):
                detail = line[7:].strip()
                current_section = "detail"
            elif line.startswith("RECOMMENDATION:"):
                current_section = "recommendation"
            elif current_section == "summary":
                summary += " " + line.strip()
            elif current_section == "detail":
                detail += "\n" + line.strip()

        insight = Insight(
            org_id=org_id,
            insight_type="friction_report",
            title=title or f"Friction: {anomaly['metric_name']}",
            summary=summary or report[:500],
            detail=detail or report,
            product_area=anomaly.get("product_area"),
            evidence_sources={
                "telemetry_anomaly": anomaly,
                "feedback_ids": [str(f.id) for f in related_feedback],
                "feedback_count": len(related_feedback),
            },
            source_count=len(related_feedback) + 1,
            confidence=min(0.9, 0.5 + len(related_feedback) * 0.05),
            generated_at=datetime.now(timezone.utc),
        )
        self.db.add(insight)
        return insight

    async def run_detection_cycle(self, org_id: uuid.UUID) -> list[Insight]:
        """Full detection cycle: find anomalies, correlate, synthesize."""
        anomalies = await self.detect_anomalies(org_id)
        insights = []

        for anomaly in anomalies:
            product_area = anomaly.get("product_area")
            if not product_area:
                continue

            # Check if we already have an active friction report for this area
            existing = await self.db.execute(
                select(Insight).where(
                    Insight.org_id == org_id,
                    Insight.insight_type == "friction_report",
                    Insight.product_area == product_area,
                    Insight.status == "active",
                )
            )
            if existing.scalar_one_or_none():
                continue

            related = await self.correlate_with_feedback(org_id, product_area)
            if related:
                insight = await self.generate_friction_report(org_id, anomaly, related)
                insights.append(insight)

                # Create a friction signal record too
                signal = FrictionSignal(
                    org_id=org_id,
                    signal_type="drop_off",
                    severity=anomaly["severity"],
                    product_area=product_area,
                    funnel_step=anomaly["metric_name"],
                    current_rate=anomaly["current_rate"],
                    baseline_rate=anomaly["baseline_rate"],
                    deviation_score=anomaly["deviation_score"],
                    affected_users=0,
                    description=insight.summary,
                    evidence=insight.evidence_sources,
                    detected_at=datetime.now(timezone.utc),
                )
                self.db.add(signal)

        if insights:
            await self.db.commit()

        logger.info(
            "friction_detection_complete",
            org_id=str(org_id),
            anomalies_found=len(anomalies),
            reports_generated=len(insights),
        )
        return insights
