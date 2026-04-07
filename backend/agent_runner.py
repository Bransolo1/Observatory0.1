"""
Observatory Agent Runner — autonomous Claude agent that executes Observatory workflows.

Usage:
  python agent_runner.py "Regenerate all intelligence"
  python agent_runner.py "Deep scan all competitors and gather market intelligence"
  python agent_runner.py  # defaults to full intelligence cycle

Requires:
  OBSERVATORY_URL, OBSERVATORY_ORG_ID, OBSERVATORY_API_KEY env vars
  ANTHROPIC_API_KEY env var (for the agent's own Claude calls)
"""

import os
import sys
import json
import httpx
import anthropic

# ─── Config ─────────────────────────────────────────────────────────────────
BASE_URL = os.environ.get("OBSERVATORY_URL", "http://localhost:8000")
ORG_ID = os.environ.get("OBSERVATORY_ORG_ID", "")
API_KEY = os.environ.get("OBSERVATORY_API_KEY", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

if not ORG_ID or not API_KEY:
    print("Error: Set OBSERVATORY_ORG_ID and OBSERVATORY_API_KEY env vars")
    sys.exit(1)
if not ANTHROPIC_KEY:
    print("Error: Set ANTHROPIC_API_KEY for the agent's own Claude calls")
    sys.exit(1)

API_V1 = f"{BASE_URL}/api/v1/orgs/{ORG_ID}"
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
TIMEOUT = 120.0

# ─── Tool definitions ──────────────────────────────────────────────────────
TOOLS = [
    # --- Read tools ---
    {
        "name": "observatory_summary",
        "description": "Get counts of all Observatory intelligence artifacts, API key status (Anthropic, Firecrawl, Perplexity).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "observatory_list_competitors",
        "description": "List all tracked competitors with their IDs and website URLs.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "observatory_list_product_areas",
        "description": "List all configured product areas.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "observatory_intelligence_feeds",
        "description": "Get the 50 most recent intelligence feed entries (scraped sites, web searches, social mentions, academic papers).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    # --- Generation tools ---
    {
        "name": "observatory_ask",
        "description": "Ask Observatory's advisor a question grounded in org context + 7-lens framework.",
        "input_schema": {
            "type": "object",
            "properties": {"question": {"type": "string", "description": "The question to ask"}},
            "required": ["question"],
        },
    },
    {
        "name": "observatory_analyze_competitor",
        "description": "Generate a 7-lens battlecard for a competitor by ID.",
        "input_schema": {
            "type": "object",
            "properties": {"competitor_id": {"type": "string", "description": "Competitor UUID"}},
            "required": ["competitor_id"],
        },
    },
    {
        "name": "observatory_friction_scenarios",
        "description": "Generate 5-7 friction scenarios based on product context.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "observatory_experiment_ideas",
        "description": "Generate 4-6 ranked experiment recommendations.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "observatory_insights",
        "description": "Synthesize cross-cutting insights from all intelligence.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "observatory_research_gaps",
        "description": "Detect knowledge gaps and generate research briefs.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "observatory_digest",
        "description": "Generate an executive intelligence digest.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    # --- Intelligence gathering tools ---
    {
        "name": "observatory_scrape_competitor",
        "description": "Scrape a competitor's website with Firecrawl. Returns extracted markdown content. Requires Firecrawl API key.",
        "input_schema": {
            "type": "object",
            "properties": {"competitor_id": {"type": "string", "description": "Competitor UUID"}},
            "required": ["competitor_id"],
        },
    },
    {
        "name": "observatory_crawl_competitor",
        "description": "Deep-crawl a competitor's website (multiple pages). Returns structured content from up to max_pages pages.",
        "input_schema": {
            "type": "object",
            "properties": {
                "competitor_id": {"type": "string", "description": "Competitor UUID"},
                "max_pages": {"type": "integer", "description": "Max pages to crawl (default 10)", "default": 10},
            },
            "required": ["competitor_id"],
        },
    },
    {
        "name": "observatory_web_search",
        "description": "Search the live web via Perplexity for market intelligence. Returns answer with citations.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Search query"}},
            "required": ["query"],
        },
    },
    {
        "name": "observatory_competitor_news",
        "description": "Get latest news about a competitor via Perplexity web search.",
        "input_schema": {
            "type": "object",
            "properties": {"competitor_id": {"type": "string", "description": "Competitor UUID"}},
            "required": ["competitor_id"],
        },
    },
    {
        "name": "observatory_hackernews_scan",
        "description": "Scan HackerNews for mentions. Free, no API key needed. Defaults to all competitor names if no query given.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Search query (optional)", "default": ""}},
            "required": [],
        },
    },
    {
        "name": "observatory_reddit_scan",
        "description": "Scan Reddit for mentions and discussions. Free, no API key needed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (optional)", "default": ""},
                "subreddit": {"type": "string", "description": "Specific subreddit to search (optional)", "default": ""},
            },
            "required": [],
        },
    },
    {
        "name": "observatory_scan_reviews",
        "description": "Scan for competitor reviews on G2, Trustpilot, App Store etc. Uses Perplexity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "competitor_id": {"type": "string", "description": "Competitor UUID"},
                "platform": {"type": "string", "description": "Platform filter: g2, trustpilot, app_store, google_play", "default": ""},
            },
            "required": ["competitor_id"],
        },
    },
    {
        "name": "observatory_academic_search",
        "description": "Search for academic papers relevant to your domain. Uses Google Scholar or Perplexity.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Academic search query"}},
            "required": ["query"],
        },
    },
    {
        "name": "observatory_deep_analysis",
        "description": "Run a comprehensive deep analysis on a competitor. Scrapes website, searches news, scans social media, then synthesizes through 7-lens framework. Most thorough analysis available.",
        "input_schema": {
            "type": "object",
            "properties": {"competitor_id": {"type": "string", "description": "Competitor UUID"}},
            "required": ["competitor_id"],
        },
    },
]


# ─── Tool executor ──────────────────────────────────────────────────────────
TOOL_ROUTES = {
    # GET endpoints
    "observatory_summary": ("GET", "/ai/summary"),
    "observatory_list_competitors": ("GET", "/competitors"),
    "observatory_list_product_areas": ("GET", "/product-areas"),
    "observatory_intelligence_feeds": ("GET", "/intel/feeds"),
    # POST endpoints (no body args)
    "observatory_friction_scenarios": ("POST", "/ai/friction-scenarios"),
    "observatory_experiment_ideas": ("POST", "/ai/experiment-ideas"),
    "observatory_insights": ("POST", "/ai/insights"),
    "observatory_research_gaps": ("POST", "/ai/research-gaps"),
    "observatory_digest": ("POST", "/ai/digest"),
}


def execute_tool(name: str, args: dict) -> str:
    try:
        # Simple route-based tools
        if name in TOOL_ROUTES:
            method, path = TOOL_ROUTES[name]
            if method == "GET":
                r = httpx.get(f"{API_V1}{path}", headers=HEADERS, timeout=TIMEOUT)
            else:
                r = httpx.post(f"{API_V1}{path}", headers=HEADERS, json={}, timeout=TIMEOUT)
            r.raise_for_status()
            return json.dumps(r.json(), indent=2)

        # Tools with path params
        if name == "observatory_ask":
            r = httpx.post(f"{API_V1}/ai/ask", headers=HEADERS, json={"question": args["question"]}, timeout=TIMEOUT)
        elif name == "observatory_analyze_competitor":
            r = httpx.post(f"{API_V1}/competitors/{args['competitor_id']}/analyze", headers=HEADERS, json={}, timeout=TIMEOUT)
        # Intel gathering tools
        elif name == "observatory_scrape_competitor":
            r = httpx.post(f"{API_V1}/intel/scrape-competitor", headers=HEADERS, json={"competitor_id": args["competitor_id"]}, timeout=TIMEOUT)
        elif name == "observatory_crawl_competitor":
            r = httpx.post(f"{API_V1}/intel/crawl-competitor", headers=HEADERS, json={"competitor_id": args["competitor_id"], "max_pages": args.get("max_pages", 10)}, timeout=TIMEOUT)
        elif name == "observatory_web_search":
            r = httpx.post(f"{API_V1}/intel/web-search", headers=HEADERS, json={"query": args["query"]}, timeout=TIMEOUT)
        elif name == "observatory_competitor_news":
            r = httpx.post(f"{API_V1}/intel/competitor-news", headers=HEADERS, json={"competitor_id": args["competitor_id"]}, timeout=TIMEOUT)
        elif name == "observatory_hackernews_scan":
            r = httpx.post(f"{API_V1}/intel/hackernews-scan", headers=HEADERS, json={"query": args.get("query", "")}, timeout=TIMEOUT)
        elif name == "observatory_reddit_scan":
            body = {}
            if args.get("query"):
                body["query"] = args["query"]
            if args.get("subreddit"):
                body["subreddit"] = args["subreddit"]
            r = httpx.post(f"{API_V1}/intel/reddit-scan", headers=HEADERS, json=body, timeout=TIMEOUT)
        elif name == "observatory_scan_reviews":
            body = {"competitor_id": args["competitor_id"]}
            if args.get("platform"):
                body["platform"] = args["platform"]
            r = httpx.post(f"{API_V1}/intel/scan-reviews", headers=HEADERS, json=body, timeout=TIMEOUT)
        elif name == "observatory_academic_search":
            r = httpx.post(f"{API_V1}/intel/academic-search", headers=HEADERS, json={"query": args["query"]}, timeout=TIMEOUT)
        elif name == "observatory_deep_analysis":
            r = httpx.post(f"{API_V1}/intel/deep-analysis", headers=HEADERS, json={"competitor_id": args["competitor_id"]}, timeout=180.0)
        else:
            return json.dumps({"error": f"Unknown tool: {name}"})

        r.raise_for_status()
        return json.dumps(r.json(), indent=2)
    except httpx.HTTPStatusError as e:
        return json.dumps({"error": f"HTTP {e.response.status_code}: {e.response.text[:500]}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ─── Agent loop ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are an autonomous Observatory agent. Observatory is a consumer intelligence platform with two capabilities:

**Intelligence Gathering** (real-time external data):
- Scrape competitor websites (Firecrawl) — pricing, features, positioning
- Web search (Perplexity) — news, trends, market moves
- Social listening (HackerNews, Reddit) — free, always available
- Review scanning — G2, Trustpilot, App Store reviews
- Academic search — research papers and studies
- Deep analysis — combines all sources for comprehensive competitor intel

**Intelligence Generation** (Claude-powered analysis):
- Competitor battlecards (7-lens analysis)
- Friction scenarios (drop-offs, rage clicks)
- Experiment recommendations (ranked by confidence)
- Cross-cutting insights (synthesized from all streams)
- Research briefs (knowledge gaps with methodology + cost)
- Intelligence digests (executive summaries)

**Optimal workflow for comprehensive intelligence:**
1. Check summary to see what exists and which API keys are configured
2. List competitors and product areas for context
3. GATHER: Scan HN + Reddit (always free), then scrape competitors and search news (if keys available)
4. GENERATE: Friction scenarios → experiment ideas → analyze competitors → insights → research gaps → digest

The gathering step enriches all subsequent generation with real-world data.

Be methodical. Report what you did at the end."""


def run_agent(task: str):
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    messages = [{"role": "user", "content": task}]

    print(f"\n{'='*60}")
    print(f"Observatory Agent — Task: {task}")
    print(f"{'='*60}\n")

    for iteration in range(25):  # max iterations safety (increased for intel gathering)
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        # Collect text and tool_use blocks
        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        # Print any text blocks
        for block in assistant_content:
            if block.type == "text":
                print(f"\n{block.text}")

        # If done, break
        if response.stop_reason == "end_turn":
            print(f"\n{'='*60}")
            print(f"Agent completed in {iteration + 1} iterations.")
            print(f"{'='*60}")
            break

        # Execute tool calls
        tool_results = []
        for block in assistant_content:
            if block.type == "tool_use":
                print(f"\n  -> Calling {block.name}({json.dumps(block.input) if block.input else ''})...")
                result = execute_tool(block.name, block.input)
                # Truncate for display
                display = result[:300] + "..." if len(result) > 300 else result
                print(f"  <- {display}")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        if tool_results:
            messages.append({"role": "user", "content": tool_results})
    else:
        print("\nAgent hit max iterations (25). Stopping.")


if __name__ == "__main__":
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else (
        "Run a full intelligence cycle: "
        "1) Gather real-time intel — scan HackerNews and Reddit for all competitors, "
        "scrape competitor websites if Firecrawl is available, search for competitor news if Perplexity is available. "
        "2) Generate analysis — friction scenarios, experiment ideas, analyze all competitors (enriched with gathered intel), "
        "synthesize insights, detect research gaps, and produce an executive digest."
    )
    run_agent(task)
