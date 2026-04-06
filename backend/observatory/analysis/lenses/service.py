"""Analytical lenses service — applies Academic, Business, and UX perspectives."""

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from observatory.core.llm import get_llm_service

logger = structlog.get_logger()

# Extended lens system prompts for deep analysis
LENS_ANALYSIS_PROMPTS = {
    "academic": (
        "You are an academic researcher analyzing product and market intelligence. "
        "Apply frameworks from peer-reviewed research (behavioral economics, HCI, cognitive psychology). "
        "Reference specific studies, theories, or methodologies where applicable. "
        "Focus on: statistical rigor, causal inference, effect sizes, replication concerns, "
        "and theoretical grounding. Cite frameworks like Jobs-to-be-Done, Technology Acceptance Model, "
        "Diffusion of Innovations, or Prospect Theory where relevant. "
        "Structure your analysis with: KEY FINDING, THEORETICAL FRAMEWORK, EVIDENCE QUALITY, "
        "IMPLICATIONS, LIMITATIONS."
    ),
    "business": (
        "You are a senior product strategist analyzing intelligence for business impact. "
        "Focus on ROI, market positioning, revenue impact, and competitive advantage. "
        "Apply frameworks like Porter's Five Forces, Blue Ocean Strategy, Jobs-to-be-Done, "
        "Value Chain Analysis, and pragmatic growth metrics (LTV, CAC, NRR, expansion revenue). "
        "Quantify impact where possible. Consider build-vs-buy, opportunity cost, and time-to-value. "
        "Structure your analysis with: BUSINESS IMPACT, STRATEGIC IMPLICATIONS, ROI ESTIMATE, "
        "RISK FACTORS, RECOMMENDED ACTION."
    ),
    "ux": (
        "You are a UX research lead analyzing intelligence through a user experience lens. "
        "Apply usability heuristics (Nielsen), accessibility standards (WCAG), "
        "information architecture principles, and interaction design patterns. "
        "Reference Baymard Institute benchmarks, NNG research, and established UX metrics "
        "(SUS, CSAT, task completion rate, time-on-task, error rate). "
        "Focus on user impact, friction points, cognitive load, and design opportunities. "
        "Structure your analysis with: USER IMPACT, HEURISTIC EVALUATION, FRICTION ANALYSIS, "
        "DESIGN OPPORTUNITY, MEASUREMENT PLAN."
    ),
}


class AnalyticalLensService:
    """Applies multi-lens analysis to intelligence data."""

    def __init__(self, db: AsyncSession | None = None, org_id: uuid.UUID | None = None):
        self.db = db
        self.org_id = org_id
        self.llm = get_llm_service()

    async def analyze_with_all_lenses(
        self, content: str, context: str = "", content_type: str = "intelligence"
    ) -> dict[str, str]:
        """Apply all three analytical lenses to content. Returns dict with academic/business/ux keys."""
        results = {}
        for lens in ("academic", "business", "ux"):
            results[lens] = await self.analyze_with_lens(content, lens, context, content_type)
        return results

    async def analyze_with_lens(
        self,
        content: str,
        lens: str,
        context: str = "",
        content_type: str = "intelligence",
    ) -> str:
        """Apply a single analytical lens to content."""
        if lens not in LENS_ANALYSIS_PROMPTS:
            raise ValueError(f"Unknown lens: {lens}. Must be one of: academic, business, ux")

        system_prompt = LENS_ANALYSIS_PROMPTS[lens]

        prompt = f"Analyze the following {content_type} through your specialized lens:\n\n"
        if context:
            prompt += f"CONTEXT:\n{context}\n\n"
        prompt += f"CONTENT:\n{content}"

        try:
            response = await self.llm.complete(
                prompt=prompt,
                system=system_prompt,
                tier="SYNTHESIS",
            )
            return response
        except Exception as e:
            logger.error("lens_analysis_error", lens=lens, error=str(e))
            return f"Analysis unavailable: {str(e)}"

    async def analyze_friction_signal(self, signal_data: dict[str, Any]) -> dict[str, str]:
        """Apply all lenses to a friction signal."""
        content = (
            f"Friction Signal: {signal_data.get('signal_type', 'unknown')}\n"
            f"Product Area: {signal_data.get('product_area', 'unknown')}\n"
            f"Severity: {signal_data.get('severity', 'unknown')}\n"
            f"Affected Users: {signal_data.get('affected_users', 'unknown')}\n"
            f"Deviation Score: {signal_data.get('deviation_score', 'N/A')}\n"
            f"Evidence: {signal_data.get('evidence', {})}"
        )
        return await self.analyze_with_all_lenses(content, content_type="friction signal")

    async def analyze_competitor_change(self, change_data: dict[str, Any]) -> dict[str, str]:
        """Apply all lenses to a competitor change."""
        content = (
            f"Competitor: {change_data.get('competitor_name', 'unknown')}\n"
            f"Change Type: {change_data.get('change_type', 'unknown')}\n"
            f"Title: {change_data.get('title', '')}\n"
            f"Description: {change_data.get('description', '')}\n"
            f"Significance: {change_data.get('significance', 'unknown')}\n"
            f"Source: {change_data.get('source_url', 'N/A')}"
        )
        return await self.analyze_with_all_lenses(content, content_type="competitive change")

    async def analyze_feedback_cluster(
        self, theme: str, feedback_items: list[dict]
    ) -> dict[str, str]:
        """Apply all lenses to a cluster of related feedback."""
        samples = feedback_items[:10]
        feedback_text = "\n".join(
            f"- [{f.get('sentiment', '?')}] {f.get('text', '')[:200]}"
            for f in samples
        )
        content = (
            f"Feedback Theme: {theme}\n"
            f"Total Items: {len(feedback_items)}\n"
            f"Sample Feedback:\n{feedback_text}"
        )
        return await self.analyze_with_all_lenses(content, content_type="feedback cluster")

    async def generate_deep_dive(
        self, topic: str, evidence: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Generate a comprehensive deep-dive analysis combining all lenses."""
        evidence_text = "\n\n".join(
            f"[{e.get('type', 'evidence')}] {e.get('title', '')}: {e.get('content', '')[:500]}"
            for e in evidence[:20]
        )

        # Get individual lens analyses
        lenses = await self.analyze_with_all_lenses(
            content=evidence_text,
            context=f"Deep-dive analysis topic: {topic}",
            content_type="evidence collection",
        )

        # Synthesize across lenses
        synthesis_prompt = (
            f"You have three expert analyses of '{topic}':\n\n"
            f"ACADEMIC PERSPECTIVE:\n{lenses['academic'][:1500]}\n\n"
            f"BUSINESS PERSPECTIVE:\n{lenses['business'][:1500]}\n\n"
            f"UX PERSPECTIVE:\n{lenses['ux'][:1500]}\n\n"
            "Synthesize these into a unified executive brief. Identify where the perspectives "
            "agree, where they conflict, and what the combined evidence suggests. "
            "Format as: EXECUTIVE SUMMARY (2-3 sentences), KEY INSIGHTS (bulleted), "
            "CROSS-LENS TENSIONS (if any), RECOMMENDED ACTIONS (prioritized list), "
            "CONFIDENCE LEVEL (low/medium/high with reasoning)."
        )

        try:
            synthesis = await self.llm.complete(
                prompt=synthesis_prompt, tier="SYNTHESIS"
            )
        except Exception as e:
            logger.error("deep_dive_synthesis_error", error=str(e))
            synthesis = "Synthesis unavailable."

        return {
            "topic": topic,
            "lenses": lenses,
            "synthesis": synthesis,
            "evidence_count": len(evidence),
            "generated_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat(),
        }
