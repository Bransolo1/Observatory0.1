"""
Observatory Agent Runner — autonomous Claude agent that executes Observatory workflows.

Usage:
  python agent_runner.py "Regenerate all intelligence"
  python agent_runner.py "Analyze our top competitor and generate friction scenarios"
  python agent_runner.py  # defaults to full nightly regeneration

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

# ─── Tool definitions (same as MCP server) ──────────────────────────────────
TOOLS = [
    {
        "name": "observatory_summary",
        "description": "Get counts of all Observatory intelligence artifacts and API key status.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "observatory_list_competitors",
        "description": "List all tracked competitors with their IDs.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "observatory_list_product_areas",
        "description": "List all configured product areas.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
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
]


# ─── Tool executor ──────────────────────────────────────────────────────────
def execute_tool(name: str, args: dict) -> str:
    try:
        if name == "observatory_summary":
            r = httpx.get(f"{API_V1}/ai/summary", headers=HEADERS, timeout=TIMEOUT)
        elif name == "observatory_list_competitors":
            r = httpx.get(f"{API_V1}/competitors", headers=HEADERS, timeout=TIMEOUT)
        elif name == "observatory_list_product_areas":
            r = httpx.get(f"{API_V1}/product-areas", headers=HEADERS, timeout=TIMEOUT)
        elif name == "observatory_ask":
            r = httpx.post(f"{API_V1}/ai/ask", headers=HEADERS, json={"question": args["question"]}, timeout=TIMEOUT)
        elif name == "observatory_analyze_competitor":
            r = httpx.post(f"{API_V1}/competitors/{args['competitor_id']}/analyze", headers=HEADERS, json={}, timeout=TIMEOUT)
        elif name == "observatory_friction_scenarios":
            r = httpx.post(f"{API_V1}/ai/friction-scenarios", headers=HEADERS, json={}, timeout=TIMEOUT)
        elif name == "observatory_experiment_ideas":
            r = httpx.post(f"{API_V1}/ai/experiment-ideas", headers=HEADERS, json={}, timeout=TIMEOUT)
        elif name == "observatory_insights":
            r = httpx.post(f"{API_V1}/ai/insights", headers=HEADERS, json={}, timeout=TIMEOUT)
        elif name == "observatory_research_gaps":
            r = httpx.post(f"{API_V1}/ai/research-gaps", headers=HEADERS, json={}, timeout=TIMEOUT)
        elif name == "observatory_digest":
            r = httpx.post(f"{API_V1}/ai/digest", headers=HEADERS, json={}, timeout=TIMEOUT)
        else:
            return json.dumps({"error": f"Unknown tool: {name}"})

        r.raise_for_status()
        return json.dumps(r.json(), indent=2)
    except httpx.HTTPStatusError as e:
        return json.dumps({"error": f"HTTP {e.response.status_code}: {e.response.text[:500]}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ─── Agent loop ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are an autonomous Observatory agent. Observatory is a consumer intelligence platform that uses Claude to generate:
- Competitor battlecards (7-lens analysis)
- Friction scenarios (drop-offs, rage clicks)
- Experiment recommendations (ranked by confidence)
- Cross-cutting insights (synthesized from all streams)
- Research briefs (knowledge gaps with methodology + cost)
- Intelligence digests (executive summaries)

You have tools to interact with the Observatory API. Execute the user's request by calling the appropriate tools in sequence. When generating intelligence, a good order is:
1. Check summary to see what exists
2. List competitors and product areas for context
3. Generate friction scenarios
4. Generate experiment ideas
5. Analyze competitors (one at a time by ID)
6. Synthesize insights (uses all prior intelligence)
7. Detect research gaps
8. Generate digest (summarizes everything)

Be methodical. Report what you did at the end."""


def run_agent(task: str):
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    messages = [{"role": "user", "content": task}]

    print(f"\n{'='*60}")
    print(f"Observatory Agent — Task: {task}")
    print(f"{'='*60}\n")

    for iteration in range(20):  # max iterations safety
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
                print(f"\n  → Calling {block.name}({json.dumps(block.input) if block.input else ''})...")
                result = execute_tool(block.name, block.input)
                # Truncate for display
                display = result[:200] + "..." if len(result) > 200 else result
                print(f"  ← {display}")
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        if tool_results:
            messages.append({"role": "user", "content": tool_results})
    else:
        print("\nAgent hit max iterations (20). Stopping.")


if __name__ == "__main__":
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Run a full intelligence regeneration: generate friction scenarios, experiment ideas, analyze all competitors, synthesize insights, detect research gaps, and produce a digest."
    run_agent(task)
