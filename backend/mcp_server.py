"""
Observatory MCP Server — exposes Observatory intelligence as tools for Claude.

Usage:
  1. Create a service API key in Observatory Settings → Profile → Service API Keys
  2. Set env vars: OBSERVATORY_URL, OBSERVATORY_ORG_ID, OBSERVATORY_API_KEY
  3. Add to claude_desktop_config.json or .claude/settings.json (see mcp_config_example.json)
  4. Run: python mcp_server.py
"""

import os
import json
import httpx
from mcp.server.fastmcp import FastMCP

# ─── Config ─────────────────────────────────────────────────────────────────
BASE_URL = os.environ.get("OBSERVATORY_URL", "http://localhost:8000")
ORG_ID = os.environ.get("OBSERVATORY_ORG_ID", "")
API_KEY = os.environ.get("OBSERVATORY_API_KEY", "")

if not ORG_ID:
    raise RuntimeError("Set OBSERVATORY_ORG_ID env var")
if not API_KEY:
    raise RuntimeError("Set OBSERVATORY_API_KEY env var (a sk-obs_* service key)")

API_V1 = f"{BASE_URL}/api/v1/orgs/{ORG_ID}"
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
TIMEOUT = 120.0  # Claude generation can take a while

mcp = FastMCP("Observatory", instructions="Consumer intelligence platform — analyse competitors, surface friction, recommend experiments, and more.")


def _get(path: str) -> str:
    r = httpx.get(f"{API_V1}{path}", headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return json.dumps(r.json(), indent=2)


def _post(path: str, body: dict | None = None) -> str:
    r = httpx.post(f"{API_V1}{path}", headers=HEADERS, json=body or {}, timeout=TIMEOUT)
    r.raise_for_status()
    return json.dumps(r.json(), indent=2)


# ─── Read tools ─────────────────────────────────────────────────────────────
@mcp.tool()
def observatory_summary() -> str:
    """Get a summary of all Observatory intelligence — counts of analyses, friction scenarios, experiment ideas, and whether the Anthropic API key is configured."""
    return _get("/ai/summary")


@mcp.tool()
def observatory_list_competitors() -> str:
    """List all tracked competitors for this organisation."""
    return _get("/competitors")


@mcp.tool()
def observatory_list_product_areas() -> str:
    """List all configured product areas."""
    return _get("/product-areas")


# ─── Generation tools ──────────────────────────────────────────────────────
@mcp.tool()
def observatory_ask(question: str) -> str:
    """Ask Observatory's strategic advisor a free-form question. The answer is grounded in the organisation's product context, competitors, and 7-lens expert framework."""
    return _post("/ai/ask", {"question": question})


@mcp.tool()
def observatory_analyze_competitor(competitor_id: str) -> str:
    """Generate a full 7-lens battlecard analysis for a specific competitor. Pass the competitor's ID (get it from observatory_list_competitors)."""
    return _post(f"/competitors/{competitor_id}/analyze")


@mcp.tool()
def observatory_friction_scenarios() -> str:
    """Generate friction scenarios — plausible drop-offs, rage clicks, and funnel breaks based on the product's context. Returns 5-7 hypothesised signals."""
    return _post("/ai/friction-scenarios")


@mcp.tool()
def observatory_experiment_ideas() -> str:
    """Generate ranked experiment recommendations weighted by the organisation's 7-lens framework. Returns 4-6 prioritised ideas."""
    return _post("/ai/experiment-ideas")


@mcp.tool()
def observatory_insights() -> str:
    """Synthesize cross-cutting insights from all existing intelligence streams (friction, competitors, experiments). Returns 4-6 findings with lens analysis."""
    return _post("/ai/insights")


@mcp.tool()
def observatory_research_gaps() -> str:
    """Detect knowledge gaps and generate structured research briefs with methodology, cost, timeline, and expected value."""
    return _post("/ai/research-gaps")


@mcp.tool()
def observatory_digest() -> str:
    """Generate an executive intelligence digest summarising all available intelligence — competitive moves, friction, experiments, and research priorities."""
    return _post("/ai/digest")


if __name__ == "__main__":
    mcp.run()
