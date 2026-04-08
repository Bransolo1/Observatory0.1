"""
Observatory Cost Controls — Hard spending limits for ALL external API calls.

This module tracks every paid API call, enforces per-org daily/monthly budgets,
and provides a dashboard endpoint for real-time spend visibility.

CRITICAL: This exists to prevent runaway costs. All limits are HARD — requests
are rejected when budgets are exhausted, not just logged.
"""

import sqlite3
import json
import time
import threading
from datetime import datetime, timezone
from dataclasses import dataclass


# ─── Pricing tables (£ GBP, updated 2025) ──────────────────────────────────
# Source: official pricing pages. We overestimate slightly for safety.

ANTHROPIC_PRICING = {
    # Per million tokens (input / output)
    "claude-sonnet-4-5-20250929": {"input": 2.40, "output": 12.00},   # £/M tokens
    "claude-sonnet-4-20250514":   {"input": 2.40, "output": 12.00},
    "claude-opus-4-20250514":     {"input": 12.00, "output": 60.00},
    "claude-haiku-4-5-20251001":  {"input": 0.64, "output": 2.56},
    # Fallback for unknown models — use most expensive
    "_default":                   {"input": 12.00, "output": 60.00},
}

PERPLEXITY_PRICING = {
    "sonar":      0.008,   # £ per request (approx $0.01)
    "sonar-pro":  0.024,   # £ per request
    "_default":   0.024,
}

FIRECRAWL_PRICING = {
    "scrape":  0.008,   # £ per page scraped (approx $0.01)
    "crawl":   0.008,   # £ per page in crawl
    "_default": 0.008,
}

SERPAPI_PRICING = {
    "google_scholar": 0.016,  # £ per search
    "_default":       0.016,
}

# Free APIs (HN Algolia, Reddit public) — tracked but no cost
FREE_APIS = {"hackernews", "reddit"}


# ─── Default budget limits (£ GBP) ─────────────────────────────────────────

@dataclass
class BudgetLimits:
    """Per-org spending limits. All values in £ GBP."""
    # Daily hard caps
    daily_anthropic: float = 5.00
    daily_perplexity: float = 2.00
    daily_firecrawl: float = 2.00
    daily_serpapi: float = 1.00
    daily_total: float = 10.00

    # Monthly hard caps
    monthly_anthropic: float = 50.00
    monthly_perplexity: float = 20.00
    monthly_firecrawl: float = 20.00
    monthly_serpapi: float = 10.00
    monthly_total: float = 80.00

    # Per-request safety caps
    max_tokens_per_request: int = 8192
    max_chat_iterations: int = 15       # was 25 — reduced
    max_specialist_iterations: int = 6  # was 10 — reduced
    max_crawl_pages: int = 5            # was 10 — reduced
    max_specialist_consults_per_turn: int = 4  # prevent consulting all 8

    # Rate limiting (requests per minute per org)
    rpm_anthropic: int = 20
    rpm_perplexity: int = 10
    rpm_firecrawl: int = 5


DEFAULT_LIMITS = BudgetLimits()


# ─── DB schema ──────────────────────────────────────────────────────────────

COST_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS api_cost_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id TEXT NOT NULL,
    service TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    model TEXT,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    estimated_cost_gbp REAL NOT NULL,
    metadata_json TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cost_log_org_date
    ON api_cost_log (org_id, created_at);

CREATE INDEX IF NOT EXISTS idx_cost_log_service
    ON api_cost_log (org_id, service, created_at);

CREATE TABLE IF NOT EXISTS org_budget_config (
    org_id TEXT PRIMARY KEY,
    limits_json TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);
"""


def init_cost_tables(conn: sqlite3.Connection):
    """Create cost tracking tables. Call during init_db()."""
    conn.executescript(COST_TABLES_SQL)
    conn.commit()


# ─── Cost tracker (thread-safe singleton) ───────────────────────────────────

class CostTracker:
    """Thread-safe cost tracking and budget enforcement."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._rpm_windows = {}  # {(org_id, service): [timestamps]}
        return cls._instance

    def _get_db(self):
        from dev_server import get_db
        return get_db()

    def _get_limits(self, org_id: str) -> BudgetLimits:
        """Get org-specific limits, falling back to defaults."""
        try:
            conn = self._get_db()
            row = conn.execute(
                "SELECT limits_json FROM org_budget_config WHERE org_id = ?",
                (org_id,)
            ).fetchone()
            conn.close()
            if row:
                data = json.loads(row["limits_json"])
                limits = BudgetLimits()
                for k, v in data.items():
                    if hasattr(limits, k):
                        setattr(limits, k, type(getattr(limits, k))(v))
                return limits
        except Exception:
            pass
        return DEFAULT_LIMITS

    def _today_str(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _month_str(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m")

    def get_daily_spend(self, org_id: str, service: str | None = None) -> float:
        """Get total spend today for an org, optionally filtered by service."""
        conn = self._get_db()
        today = self._today_str()
        if service:
            row = conn.execute(
                "SELECT COALESCE(SUM(estimated_cost_gbp), 0) as total FROM api_cost_log WHERE org_id = ? AND service = ? AND created_at >= ?",
                (org_id, service, today)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COALESCE(SUM(estimated_cost_gbp), 0) as total FROM api_cost_log WHERE org_id = ? AND created_at >= ?",
                (org_id, today)
            ).fetchone()
        conn.close()
        return float(row["total"])

    def get_monthly_spend(self, org_id: str, service: str | None = None) -> float:
        """Get total spend this month for an org."""
        conn = self._get_db()
        month_start = self._month_str() + "-01"
        if service:
            row = conn.execute(
                "SELECT COALESCE(SUM(estimated_cost_gbp), 0) as total FROM api_cost_log WHERE org_id = ? AND service = ? AND created_at >= ?",
                (org_id, service, month_start)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COALESCE(SUM(estimated_cost_gbp), 0) as total FROM api_cost_log WHERE org_id = ? AND created_at >= ?",
                (org_id, month_start)
            ).fetchone()
        conn.close()
        return float(row["total"])

    def check_rpm(self, org_id: str, service: str, limits: BudgetLimits) -> bool:
        """Check if we're within rate limits. Returns True if OK."""
        key = (org_id, service)
        now = time.time()
        window = 60.0  # 1 minute

        with self._lock:
            if key not in self._rpm_windows:
                self._rpm_windows[key] = []

            # Clean old entries
            self._rpm_windows[key] = [t for t in self._rpm_windows[key] if now - t < window]

            rpm_limit = getattr(limits, f"rpm_{service}", 30)
            if len(self._rpm_windows[key]) >= rpm_limit:
                return False

            self._rpm_windows[key].append(now)
            return True

    def check_budget(self, org_id: str, service: str, estimated_cost: float) -> tuple[bool, str]:
        """
        Check if a request is within budget. Returns (allowed, reason).
        This is the CRITICAL gate — if this returns False, the request MUST be rejected.
        """
        limits = self._get_limits(org_id)

        # 1. Rate limit check
        if not self.check_rpm(org_id, service, limits):
            return False, f"Rate limit exceeded for {service}. Try again in a minute."

        # 2. Daily service-specific limit
        daily_limit = getattr(limits, f"daily_{service}", 5.0)
        daily_spend = self.get_daily_spend(org_id, service)
        if daily_spend + estimated_cost > daily_limit:
            return False, f"Daily {service} budget exhausted: £{daily_spend:.2f}/£{daily_limit:.2f} spent today."

        # 3. Daily total limit
        daily_total = self.get_daily_spend(org_id)
        if daily_total + estimated_cost > limits.daily_total:
            return False, f"Daily total budget exhausted: £{daily_total:.2f}/£{limits.daily_total:.2f} spent today."

        # 4. Monthly service-specific limit
        monthly_limit = getattr(limits, f"monthly_{service}", 20.0)
        monthly_spend = self.get_monthly_spend(org_id, service)
        if monthly_spend + estimated_cost > monthly_limit:
            return False, f"Monthly {service} budget exhausted: £{monthly_spend:.2f}/£{monthly_limit:.2f} this month."

        # 5. Monthly total limit
        monthly_total = self.get_monthly_spend(org_id)
        if monthly_total + estimated_cost > limits.monthly_total:
            return False, f"Monthly total budget exhausted: £{monthly_total:.2f}/£{limits.monthly_total:.2f} this month."

        return True, "OK"

    def log_cost(self, org_id: str, service: str, endpoint: str,
                 estimated_cost: float, model: str | None = None,
                 input_tokens: int = 0, output_tokens: int = 0,
                 metadata: dict | None = None):
        """Log a completed API call and its cost."""
        conn = self._get_db()
        conn.execute(
            """INSERT INTO api_cost_log
               (org_id, service, endpoint, model, input_tokens, output_tokens, estimated_cost_gbp, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (org_id, service, endpoint, model, input_tokens, output_tokens,
             estimated_cost, json.dumps(metadata) if metadata else None)
        )
        conn.commit()
        conn.close()

    def estimate_anthropic_cost(self, model: str, input_tokens: int, max_output_tokens: int) -> float:
        """Estimate cost for an Anthropic API call. Uses max_output_tokens as worst case."""
        pricing = ANTHROPIC_PRICING.get(model, ANTHROPIC_PRICING["_default"])
        # Cost = (input_tokens / 1M * input_price) + (max_output_tokens / 1M * output_price)
        cost = (input_tokens / 1_000_000 * pricing["input"]) + \
               (max_output_tokens / 1_000_000 * pricing["output"])
        return cost

    def actual_anthropic_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Calculate actual cost from a completed Anthropic API call."""
        pricing = ANTHROPIC_PRICING.get(model, ANTHROPIC_PRICING["_default"])
        return (input_tokens / 1_000_000 * pricing["input"]) + \
               (output_tokens / 1_000_000 * pricing["output"])

    def estimate_perplexity_cost(self, model: str = "sonar") -> float:
        return PERPLEXITY_PRICING.get(model, PERPLEXITY_PRICING["_default"])

    def estimate_firecrawl_cost(self, operation: str = "scrape", pages: int = 1) -> float:
        per_page = FIRECRAWL_PRICING.get(operation, FIRECRAWL_PRICING["_default"])
        return per_page * pages

    def estimate_serpapi_cost(self) -> float:
        return SERPAPI_PRICING["_default"]

    def get_spend_summary(self, org_id: str) -> dict:
        """Get comprehensive spend summary for dashboard display."""
        limits = self._get_limits(org_id)
        conn = self._get_db()
        today = self._today_str()
        month_start = self._month_str() + "-01"

        # Daily breakdown by service
        daily_rows = conn.execute(
            "SELECT service, COALESCE(SUM(estimated_cost_gbp), 0) as total, COUNT(*) as calls FROM api_cost_log WHERE org_id = ? AND created_at >= ? GROUP BY service",
            (org_id, today)
        ).fetchall()

        # Monthly breakdown by service
        monthly_rows = conn.execute(
            "SELECT service, COALESCE(SUM(estimated_cost_gbp), 0) as total, COUNT(*) as calls FROM api_cost_log WHERE org_id = ? AND created_at >= ? GROUP BY service",
            (org_id, month_start)
        ).fetchall()

        # Last 20 calls
        recent = conn.execute(
            "SELECT service, endpoint, model, estimated_cost_gbp, input_tokens, output_tokens, created_at FROM api_cost_log WHERE org_id = ? ORDER BY created_at DESC LIMIT 20",
            (org_id,)
        ).fetchall()

        conn.close()

        daily_by_service = {r["service"]: {"spend": round(r["total"], 4), "calls": r["calls"]} for r in daily_rows}
        monthly_by_service = {r["service"]: {"spend": round(r["total"], 4), "calls": r["calls"]} for r in monthly_rows}

        daily_total = sum(r["total"] for r in daily_rows)
        monthly_total = sum(r["total"] for r in monthly_rows)

        return {
            "daily": {
                "total_spend": round(daily_total, 4),
                "total_limit": limits.daily_total,
                "remaining": round(limits.daily_total - daily_total, 4),
                "by_service": daily_by_service,
            },
            "monthly": {
                "total_spend": round(monthly_total, 4),
                "total_limit": limits.monthly_total,
                "remaining": round(limits.monthly_total - monthly_total, 4),
                "by_service": monthly_by_service,
            },
            "limits": {
                "daily_anthropic": limits.daily_anthropic,
                "daily_perplexity": limits.daily_perplexity,
                "daily_firecrawl": limits.daily_firecrawl,
                "daily_serpapi": limits.daily_serpapi,
                "daily_total": limits.daily_total,
                "monthly_anthropic": limits.monthly_anthropic,
                "monthly_perplexity": limits.monthly_perplexity,
                "monthly_firecrawl": limits.monthly_firecrawl,
                "monthly_serpapi": limits.monthly_serpapi,
                "monthly_total": limits.monthly_total,
                "max_tokens_per_request": limits.max_tokens_per_request,
                "max_chat_iterations": limits.max_chat_iterations,
                "max_specialist_iterations": limits.max_specialist_iterations,
                "max_crawl_pages": limits.max_crawl_pages,
                "max_specialist_consults_per_turn": limits.max_specialist_consults_per_turn,
            },
            "recent_calls": [dict(r) for r in recent],
        }

    def update_limits(self, org_id: str, new_limits: dict):
        """Update org-specific budget limits."""
        conn = self._get_db()
        conn.execute(
            """INSERT INTO org_budget_config (org_id, limits_json, updated_at)
               VALUES (?, ?, datetime('now'))
               ON CONFLICT(org_id) DO UPDATE SET limits_json = ?, updated_at = datetime('now')""",
            (org_id, json.dumps(new_limits), json.dumps(new_limits))
        )
        conn.commit()
        conn.close()


# ─── Convenience singleton ──────────────────────────────────────────────────
tracker = CostTracker()


# ─── Guard functions (use these in endpoints) ──────────────────────────────

def guard_anthropic(org_id: str, model: str, max_tokens: int) -> tuple[bool, str]:
    """Check budget before an Anthropic call. Returns (ok, reason)."""
    # Estimate worst-case cost (assume ~1000 input tokens if we don't know)
    est = tracker.estimate_anthropic_cost(model, 1000, max_tokens)
    return tracker.check_budget(org_id, "anthropic", est)


def guard_perplexity(org_id: str) -> tuple[bool, str]:
    """Check budget before a Perplexity call."""
    est = tracker.estimate_perplexity_cost()
    return tracker.check_budget(org_id, "perplexity", est)


def guard_firecrawl(org_id: str, pages: int = 1) -> tuple[bool, str]:
    """Check budget before a Firecrawl call."""
    est = tracker.estimate_firecrawl_cost("scrape", pages)
    return tracker.check_budget(org_id, "firecrawl", est)


def guard_serpapi(org_id: str) -> tuple[bool, str]:
    """Check budget before a SerpAPI call."""
    est = tracker.estimate_serpapi_cost()
    return tracker.check_budget(org_id, "serpapi", est)


def log_anthropic_usage(org_id: str, model: str, endpoint: str,
                        input_tokens: int, output_tokens: int):
    """Log actual Anthropic usage after a call completes."""
    cost = tracker.actual_anthropic_cost(model, input_tokens, output_tokens)
    tracker.log_cost(org_id, "anthropic", endpoint, cost, model=model,
                     input_tokens=input_tokens, output_tokens=output_tokens)


def log_perplexity_usage(org_id: str, endpoint: str, model: str = "sonar"):
    """Log a Perplexity call."""
    cost = tracker.estimate_perplexity_cost(model)
    tracker.log_cost(org_id, "perplexity", endpoint, cost, model=model)


def log_firecrawl_usage(org_id: str, endpoint: str, pages: int = 1):
    """Log a Firecrawl call."""
    cost = tracker.estimate_firecrawl_cost("scrape", pages)
    tracker.log_cost(org_id, "firecrawl", endpoint, cost)


def log_serpapi_usage(org_id: str, endpoint: str):
    """Log a SerpAPI call."""
    cost = tracker.estimate_serpapi_cost()
    tracker.log_cost(org_id, "serpapi", endpoint, cost)


def log_free_usage(org_id: str, service: str, endpoint: str):
    """Log a free API call (HN, Reddit) for tracking without cost."""
    tracker.log_cost(org_id, service, endpoint, 0.0)
