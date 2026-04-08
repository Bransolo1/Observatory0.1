"""
Observatory Dev Server — SQLite + Claude integration. No Docker needed.
Run: python dev_server.py
"""

import os
import uuid
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager

import httpx
import bcrypt
import uvicorn
from jose import jwt
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

import httpx

from cost_controls import (
    init_cost_tables, tracker,
    guard_anthropic, guard_perplexity, guard_firecrawl, guard_serpapi,
    log_anthropic_usage, log_perplexity_usage, log_firecrawl_usage,
    log_serpapi_usage, log_free_usage, DEFAULT_LIMITS,
)

DB_PATH = "observatory_dev.db"
JWT_SECRET = "dev-secret-change-in-production"
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_MINUTES = 60 * 24
CLAUDE_MODEL = "claude-sonnet-4-5-20250929"

# ─── Lens personas (weighted analytical perspectives) ────────────────────────
LENS_PERSONAS = {
    "academic": "Academic researcher — peer-reviewed research, JTBD, TAM, diffusion of innovations, prospect theory",
    "business": "Business strategist — ROI, LTV/CAC, Porter's forces, strategic fit, revenue model",
    "ux": "UX designer — Nielsen's 10 heuristics, Baymard benchmarks, WCAG accessibility, NNG research",
    "behavioural": "Behavioural scientist — Cialdini, Kahneman, BJ Fogg; biases, nudges, habit loops, persuasion",
    "clinical": "Clinical researcher — RCT rigour, effect sizes, confidence intervals, systematic review mindset",
    "ethnographic": "Ethnographer — contextual inquiry, diary studies, lived experience, qualitative interpretation",
    "quant": "Data scientist — causal inference, cohort analysis, segmentation, statistical significance",
}
DEFAULT_LENS_WEIGHTS = {
    "academic": 15, "business": 20, "ux": 15, "behavioural": 15,
    "clinical": 10, "ethnographic": 10, "quant": 15,
}


def merge_lens_weights(raw) -> dict:
    """Merge stored weights with defaults so new keys always exist."""
    out = dict(DEFAULT_LENS_WEIGHTS)
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(v, (int, float)):
                out[k] = int(v)
    return out


def format_lens_block(weights: dict) -> str:
    """Render the persona + weight block for Claude system prompts."""
    lines = []
    for key, pct in weights.items():
        persona = LENS_PERSONAS.get(key, key)
        lines.append(f"- [{pct}%] {persona}")
    return "\n".join(lines)


security = HTTPBearer(auto_error=False)


# ─── DB ──────────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
            hashed_password TEXT NOT NULL, avatar_url TEXT, is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS organizations (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, slug TEXT UNIQUE NOT NULL,
            description TEXT, product_description TEXT,
            is_onboarded INTEGER DEFAULT 0, onboarding_step INTEGER DEFAULT 0,
            lens_weights TEXT DEFAULT '{"academic":15,"business":20,"ux":15,"behavioural":15,"clinical":10,"ethnographic":10,"quant":15}',
            anthropic_api_key TEXT,
            is_active INTEGER DEFAULT 1, created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS organization_memberships (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            org_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            role TEXT NOT NULL DEFAULT 'viewer', created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS product_areas (
            id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            name TEXT NOT NULL, description TEXT, created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS competitors (
            id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            name TEXT NOT NULL, slug TEXT NOT NULL, website_url TEXT, description TEXT,
            analysis_json TEXT, analysis_at TEXT,
            is_active INTEGER DEFAULT 1, created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS data_sources (
            id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            source_type TEXT NOT NULL, name TEXT NOT NULL,
            status TEXT DEFAULT 'planned', created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS ai_generations (
            id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            kind TEXT NOT NULL, payload_json TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS service_api_keys (
            id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            key_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            last_used_at TEXT
        );
        CREATE TABLE IF NOT EXISTS intelligence_feeds (
            id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            source TEXT NOT NULL,
            query TEXT NOT NULL,
            result_json TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS chat_conversations (
            id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            user_id TEXT NOT NULL,
            title TEXT DEFAULT 'New conversation',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS chat_messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            tool_calls_json TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    # Migrations for existing DBs
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(organizations)").fetchall()}
    if "anthropic_api_key" not in cols:
        conn.execute("ALTER TABLE organizations ADD COLUMN anthropic_api_key TEXT")
    if "firecrawl_api_key" not in cols:
        conn.execute("ALTER TABLE organizations ADD COLUMN firecrawl_api_key TEXT")
    if "perplexity_api_key" not in cols:
        conn.execute("ALTER TABLE organizations ADD COLUMN perplexity_api_key TEXT")
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(competitors)").fetchall()}
    if "analysis_json" not in cols:
        conn.execute("ALTER TABLE competitors ADD COLUMN analysis_json TEXT")
        conn.execute("ALTER TABLE competitors ADD COLUMN analysis_at TEXT")
    # Init cost tracking tables
    init_cost_tables(conn)
    # Migrate existing orgs: merge lens_weights with new 7-lens defaults
    for org_row in conn.execute("SELECT id, lens_weights FROM organizations").fetchall():
        existing = json.loads(org_row["lens_weights"] or "{}")
        merged = merge_lens_weights(existing)
        conn.execute("UPDATE organizations SET lens_weights = ? WHERE id = ?",
                     (json.dumps(merged), org_row["id"]))
    conn.commit()
    conn.close()


# ─── Auth helpers ────────────────────────────────────────────────────────────
def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()


def verify_password(p: str, h: str) -> bool:
    return bcrypt.checkpw(p.encode(), h.encode())


def create_token(user_id: str, org_id: str | None = None, role: str | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRY_MINUTES)
    payload = {"sub": user_id, "exp": expire}
    if org_id:
        payload["org_id"] = org_id
    if role:
        payload["role"] = role
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def get_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(401, "Not authenticated")
    token = credentials.credentials
    # Service API key auth: sk-obs_*
    if token.startswith("sk-obs_"):
        conn = get_db()
        rows = conn.execute("SELECT id, org_id, key_hash FROM service_api_keys").fetchall()
        for row in rows:
            if bcrypt.checkpw(token.encode(), row["key_hash"].encode()):
                conn.execute("UPDATE service_api_keys SET last_used_at = datetime('now') WHERE id = ?", (row["id"],))
                conn.commit(); conn.close()
                return {"sub": f"svc:{row['id']}", "org_id": row["org_id"]}
        conn.close()
        raise HTTPException(401, "Invalid service key")
    # JWT auth
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        raise HTTPException(401, "Invalid token")


def require_org(payload: dict = Depends(get_user)) -> tuple[str, str]:
    org_id = payload.get("org_id")
    if not org_id:
        raise HTTPException(403, "No organisation selected")
    return payload["sub"], org_id


def check_org(org_id: str, ctx: tuple[str, str]):
    _, token_org = ctx
    if token_org != org_id:
        raise HTTPException(403, "Org mismatch")


# ─── Claude ──────────────────────────────────────────────────────────────────
def get_org_context(conn, org_id: str) -> dict:
    org = conn.execute("SELECT * FROM organizations WHERE id = ?", (org_id,)).fetchone()
    areas = conn.execute("SELECT name FROM product_areas WHERE org_id = ?", (org_id,)).fetchall()
    comps = conn.execute("SELECT name, website_url, description FROM competitors WHERE org_id = ?", (org_id,)).fetchall()
    sources = conn.execute("SELECT source_type, name FROM data_sources WHERE org_id = ?", (org_id,)).fetchall()
    return {
        "org_name": org["name"],
        "product_description": org["product_description"] or "",
        "lens_weights": merge_lens_weights(json.loads(org["lens_weights"] or "{}")),
        "product_areas": [r["name"] for r in areas],
        "competitors": [{"name": r["name"], "website_url": r["website_url"], "description": r["description"]} for r in comps],
        "data_sources": [{"type": r["source_type"], "name": r["name"]} for r in sources],
    }


def get_recent_intel(conn, org_id: str, limit: int = 10) -> str:
    """Fetch recent intelligence feeds and format as a context block for prompts."""
    rows = conn.execute(
        "SELECT source, query, result_json, created_at FROM intelligence_feeds WHERE org_id = ? ORDER BY created_at DESC LIMIT ?",
        (org_id, limit)
    ).fetchall()
    if not rows:
        return ""
    lines = ["\n\n**Recent Intelligence (gathered from external sources):**"]
    for r in rows:
        # Summarize each feed entry concisely
        source = r["source"]
        query = r["query"]
        raw = r["result_json"]
        # Extract a brief summary from the JSON
        try:
            data = json.loads(raw)
            if source == "hackernews" and "hits" in data:
                summary = f"{len(data['hits'])} HN results for '{query}'"
            elif source == "reddit" and "posts" in data:
                summary = f"{len(data['posts'])} Reddit posts about '{query}'"
            elif source == "perplexity" and "answer" in data:
                summary = data["answer"][:200]
            elif source == "firecrawl" and "markdown" in data:
                summary = data["markdown"][:200]
            else:
                summary = str(data)[:200]
        except Exception:
            summary = raw[:200]
        lines.append(f"- [{source}] {query}: {summary}")
    return "\n".join(lines)


def get_api_key(conn, org_id: str) -> str | None:
    row = conn.execute("SELECT anthropic_api_key FROM organizations WHERE id = ?", (org_id,)).fetchone()
    key = row["anthropic_api_key"] if row else None
    return key or os.environ.get("ANTHROPIC_API_KEY") or None


def get_firecrawl_key(conn, org_id: str) -> str | None:
    row = conn.execute("SELECT firecrawl_api_key FROM organizations WHERE id = ?", (org_id,)).fetchone()
    key = row["firecrawl_api_key"] if row else None
    return key or os.environ.get("FIRECRAWL_API_KEY") or None


def get_perplexity_key(conn, org_id: str) -> str | None:
    row = conn.execute("SELECT perplexity_api_key FROM organizations WHERE id = ?", (org_id,)).fetchone()
    key = row["perplexity_api_key"] if row else None
    return key or os.environ.get("PERPLEXITY_API_KEY") or None


def firecrawl_scrape(api_key: str, url: str, org_id: str = "") -> dict:
    """Scrape a single URL with Firecrawl."""
    if org_id:
        ok, reason = guard_firecrawl(org_id, pages=1)
        if not ok:
            raise HTTPException(429, f"Cost limit reached: {reason}")
    r = httpx.post("https://api.firecrawl.dev/v1/scrape",
                   headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                   json={"url": url, "formats": ["markdown"]},
                   timeout=60.0)
    r.raise_for_status()
    if org_id:
        log_firecrawl_usage(org_id, "scrape", pages=1)
    return r.json()


def firecrawl_crawl(api_key: str, url: str, max_pages: int = 10, org_id: str = "") -> dict:
    """Crawl multiple pages with Firecrawl."""
    # Hard cap on pages
    limits = tracker._get_limits(org_id) if org_id else DEFAULT_LIMITS
    max_pages = min(max_pages, limits.max_crawl_pages)
    if org_id:
        ok, reason = guard_firecrawl(org_id, pages=max_pages)
        if not ok:
            raise HTTPException(429, f"Cost limit reached: {reason}")
    r = httpx.post("https://api.firecrawl.dev/v1/crawl",
                   headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                   json={"url": url, "limit": max_pages, "scrapeOptions": {"formats": ["markdown"]}},
                   timeout=120.0)
    r.raise_for_status()
    if org_id:
        log_firecrawl_usage(org_id, "crawl", pages=max_pages)
    return r.json()


def perplexity_search(api_key: str, query: str, org_id: str = "") -> dict:
    """Search the web with Perplexity Sonar."""
    if org_id:
        ok, reason = guard_perplexity(org_id)
        if not ok:
            raise HTTPException(429, f"Cost limit reached: {reason}")
    r = httpx.post("https://api.perplexity.ai/chat/completions",
                   headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                   json={
                       "model": "sonar",
                       "messages": [{"role": "user", "content": query}],
                   },
                   timeout=30.0)
    r.raise_for_status()
    if org_id:
        log_perplexity_usage(org_id, "web_search")
    return r.json()


def hackernews_search(query: str, hits: int = 20, org_id: str = "") -> list[dict]:
    """Search HN via Algolia (free, no auth)."""
    r = httpx.get("https://hn.algolia.com/api/v1/search",
                  params={"query": query, "tags": "story", "hitsPerPage": hits},
                  timeout=15.0)
    r.raise_for_status()
    if org_id:
        log_free_usage(org_id, "hackernews", "search")
    return r.json().get("hits", [])


def reddit_search(query: str, subreddit: str | None = None, limit: int = 25, org_id: str = "") -> list[dict]:
    """Search Reddit (free, no auth needed with User-Agent)."""
    url = f"https://old.reddit.com/r/{subreddit}/search.json" if subreddit else "https://old.reddit.com/search.json"
    r = httpx.get(url,
                  params={"q": query, "sort": "new", "limit": limit, "restrict_sr": "on" if subreddit else ""},
                  headers={"User-Agent": "Observatory/1.0 (Consumer Intelligence Platform)"},
                  timeout=15.0)
    r.raise_for_status()
    if org_id:
        log_free_usage(org_id, "reddit", "search")
    data = r.json().get("data", {}).get("children", [])
    return [c["data"] for c in data]


def save_intel_feed(conn, org_id: str, source: str, query: str, result: dict) -> str:
    """Save an intelligence feed entry and return its ID."""
    feed_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO intelligence_feeds (id, org_id, source, query, result_json, created_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
        (feed_id, org_id, source, query, json.dumps(result))
    )
    conn.commit()
    return feed_id


def claude_client(api_key: str):
    if not ANTHROPIC_AVAILABLE:
        raise HTTPException(500, "Anthropic SDK not installed")
    return anthropic.Anthropic(api_key=api_key)


def call_claude(api_key: str, system: str, user_message: str, max_tokens: int = 4000, org_id: str = "") -> str:
    # ── Cost guard ──
    limits = tracker._get_limits(org_id) if org_id else DEFAULT_LIMITS
    capped_tokens = min(max_tokens, limits.max_tokens_per_request)
    if org_id:
        ok, reason = guard_anthropic(org_id, CLAUDE_MODEL, capped_tokens)
        if not ok:
            raise HTTPException(429, f"Cost limit reached: {reason}")
    client = claude_client(api_key)
    try:
        resp = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=capped_tokens,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )
        # ── Log actual usage ──
        if org_id:
            log_anthropic_usage(org_id, CLAUDE_MODEL, "call_claude",
                                resp.usage.input_tokens, resp.usage.output_tokens)
        return resp.content[0].text
    except anthropic.AuthenticationError:
        raise HTTPException(401, "Invalid Anthropic API key. Update it in Settings.")
    except anthropic.APIError as e:
        raise HTTPException(502, f"Claude API error: {str(e)}")


def call_claude_json(api_key: str, system: str, user_message: str, max_tokens: int = 4000, org_id: str = "") -> dict:
    text = call_claude(api_key, system + "\n\nRespond with ONLY valid JSON. No markdown fences, no preamble.", user_message, max_tokens, org_id=org_id)
    # Strip fences if present
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise HTTPException(502, f"Claude returned invalid JSON: {str(e)}")


# ─── Schemas ─────────────────────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    email: EmailStr
    name: str
    password: str
    org_name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class SelectOrgRequest(BaseModel):
    org_id: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    org_id: str | None = None
    role: str | None = None


class ProductAreaIn(BaseModel):
    name: str
    description: str | None = None


class CompetitorIn(BaseModel):
    name: str
    website_url: str | None = None
    description: str | None = None


class DataSourceIn(BaseModel):
    source_type: str
    name: str


class OnboardingStepIn(BaseModel):
    step: int | None = None
    product_description: str | None = None
    lens_weights: dict | None = None
    is_onboarded: bool | None = None


class ApiKeyIn(BaseModel):
    anthropic_api_key: str


class AskIn(BaseModel):
    question: str


class IntelScrapeIn(BaseModel):
    competitor_id: str | None = None
    url: str | None = None


class IntelCrawlIn(BaseModel):
    competitor_id: str | None = None
    url: str | None = None
    max_pages: int | None = 10


class IntelWebSearchIn(BaseModel):
    query: str


class IntelCompetitorNewsIn(BaseModel):
    competitor_id: str


class IntelHNScanIn(BaseModel):
    query: str | None = None


class IntelRedditScanIn(BaseModel):
    query: str | None = None
    subreddit: str | None = None


class IntelReviewScanIn(BaseModel):
    competitor_id: str
    platform: str | None = None


class IntelAcademicIn(BaseModel):
    query: str


class IntelDeepAnalysisIn(BaseModel):
    competitor_id: str


class IntelApiKeyIn(BaseModel):
    api_key: str


# ─── Lifespan ────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    print("\n  Observatory Dev Server ready")
    print(f"  DB: {os.path.abspath(DB_PATH)}")
    print(f"  API: http://localhost:8000/api/v1")
    print(f"  Anthropic SDK: {'available' if ANTHROPIC_AVAILABLE else 'MISSING'}\n")
    yield


app = FastAPI(title="Observatory Dev", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Auth ────────────────────────────────────────────────────────────────────
@app.post("/api/v1/auth/register", response_model=AuthResponse)
def register(body: RegisterRequest):
    conn = get_db()
    if conn.execute("SELECT id FROM users WHERE email = ?", (body.email,)).fetchone():
        conn.close()
        raise HTTPException(400, "Email already registered")

    user_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO users (id, email, name, hashed_password) VALUES (?, ?, ?, ?)",
        (user_id, body.email, body.name, hash_password(body.password)),
    )

    org_id = None
    role = None
    if body.org_name:
        org_id = str(uuid.uuid4())
        slug = body.org_name.lower().replace(" ", "-").replace("_", "-")[:100]
        if conn.execute("SELECT id FROM organizations WHERE slug = ?", (slug,)).fetchone():
            slug = f"{slug}-{org_id[:8]}"
        conn.execute("INSERT INTO organizations (id, name, slug) VALUES (?, ?, ?)", (org_id, body.org_name, slug))
        role = "owner"
        conn.execute(
            "INSERT INTO organization_memberships (id, user_id, org_id, role) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), user_id, org_id, role),
        )

    conn.commit()
    conn.close()
    return AuthResponse(access_token=create_token(user_id, org_id, role), user_id=user_id, org_id=org_id, role=role)


@app.post("/api/v1/auth/login", response_model=AuthResponse)
def login(body: LoginRequest):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (body.email,)).fetchone()
    if not user or not verify_password(body.password, user["hashed_password"]):
        conn.close()
        raise HTTPException(401, "Invalid email or password")
    mem = conn.execute("SELECT org_id, role FROM organization_memberships WHERE user_id = ? LIMIT 1", (user["id"],)).fetchone()
    conn.close()
    org_id = mem["org_id"] if mem else None
    role = mem["role"] if mem else None
    return AuthResponse(access_token=create_token(user["id"], org_id, role), user_id=user["id"], org_id=org_id, role=role)


@app.get("/api/v1/auth/me")
def me(payload: dict = Depends(get_user)):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (payload["sub"],)).fetchone()
    conn.close()
    if not user:
        raise HTTPException(404, "User not found")
    return {"id": user["id"], "email": user["email"], "name": user["name"], "avatar_url": user["avatar_url"]}


@app.get("/api/v1/auth/orgs")
def my_orgs(payload: dict = Depends(get_user)):
    conn = get_db()
    rows = conn.execute(
        """SELECT o.id, o.name, o.slug, m.role, o.is_onboarded
           FROM organizations o JOIN organization_memberships m ON o.id = m.org_id
           WHERE m.user_id = ?""", (payload["sub"],)).fetchall()
    conn.close()
    return [{"id": r["id"], "name": r["name"], "slug": r["slug"], "role": r["role"], "is_onboarded": bool(r["is_onboarded"])} for r in rows]


@app.post("/api/v1/auth/select-org", response_model=AuthResponse)
def select_org(body: SelectOrgRequest, payload: dict = Depends(get_user)):
    conn = get_db()
    mem = conn.execute("SELECT role FROM organization_memberships WHERE user_id = ? AND org_id = ?", (payload["sub"], body.org_id)).fetchone()
    conn.close()
    if not mem:
        raise HTTPException(403, "Not a member")
    return AuthResponse(access_token=create_token(payload["sub"], body.org_id, mem["role"]), user_id=payload["sub"], org_id=body.org_id, role=mem["role"])


# ─── Onboarding ──────────────────────────────────────────────────────────────
@app.get("/api/v1/orgs/{org_id}/onboarding")
def get_onboarding(org_id: str, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    org = conn.execute("SELECT * FROM organizations WHERE id = ?", (org_id,)).fetchone()
    if not org:
        conn.close(); raise HTTPException(404, "Org not found")
    pa = conn.execute("SELECT COUNT(*) c FROM product_areas WHERE org_id = ?", (org_id,)).fetchone()["c"]
    cp = conn.execute("SELECT COUNT(*) c FROM competitors WHERE org_id = ?", (org_id,)).fetchone()["c"]
    ds = conn.execute("SELECT COUNT(*) c FROM data_sources WHERE org_id = ?", (org_id,)).fetchone()["c"]
    has_key = bool(org["anthropic_api_key"]) or bool(os.environ.get("ANTHROPIC_API_KEY"))
    conn.close()
    return {
        "is_onboarded": bool(org["is_onboarded"]),
        "onboarding_step": org["onboarding_step"],
        "product_description": org["product_description"],
        "lens_weights": merge_lens_weights(json.loads(org["lens_weights"] or "{}")),
        "product_areas_count": pa, "competitors_count": cp, "data_sources_count": ds,
        "has_api_key": has_key,
    }


@app.patch("/api/v1/orgs/{org_id}/onboarding")
def patch_onboarding(org_id: str, body: OnboardingStepIn, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    fields, params = [], []
    if body.step is not None:
        fields.append("onboarding_step = ?"); params.append(body.step)
    if body.product_description is not None:
        fields.append("product_description = ?"); params.append(body.product_description)
    if body.lens_weights is not None:
        fields.append("lens_weights = ?"); params.append(json.dumps(body.lens_weights))
    if body.is_onboarded is not None:
        fields.append("is_onboarded = ?"); params.append(1 if body.is_onboarded else 0)
    if fields:
        params.append(org_id)
        conn.execute(f"UPDATE organizations SET {', '.join(fields)} WHERE id = ?", params)
        conn.commit()
    conn.close()
    return {"ok": True}


# ─── API Key ─────────────────────────────────────────────────────────────────
@app.post("/api/v1/orgs/{org_id}/api-key")
def set_api_key(org_id: str, body: ApiKeyIn, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    conn.execute("UPDATE organizations SET anthropic_api_key = ? WHERE id = ?", (body.anthropic_api_key, org_id))
    conn.commit()
    conn.close()
    return {"ok": True}


# ─── Service API Keys ────────────────────────────────────────────────────────
class ServiceKeyIn(BaseModel):
    name: str


@app.get("/api/v1/orgs/{org_id}/service-keys")
def list_service_keys(org_id: str, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    rows = conn.execute(
        "SELECT id, name, created_at, last_used_at FROM service_api_keys WHERE org_id = ? ORDER BY created_at DESC",
        (org_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/v1/orgs/{org_id}/service-keys")
def create_service_key(org_id: str, body: ServiceKeyIn, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    key_id = str(uuid.uuid4())
    plaintext = f"sk-obs_{uuid.uuid4().hex}"
    key_hash = bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt()).decode()
    conn = get_db()
    conn.execute(
        "INSERT INTO service_api_keys (id, org_id, key_hash, name) VALUES (?, ?, ?, ?)",
        (key_id, org_id, key_hash, body.name),
    )
    conn.commit()
    conn.close()
    return {"id": key_id, "name": body.name, "key": plaintext, "created_at": datetime.now(timezone.utc).isoformat()}


@app.delete("/api/v1/orgs/{org_id}/service-keys/{key_id}")
def delete_service_key(org_id: str, key_id: str, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    conn.execute("DELETE FROM service_api_keys WHERE id = ? AND org_id = ?", (key_id, org_id))
    conn.commit()
    conn.close()
    return {"ok": True}


# ─── Product Areas ───────────────────────────────────────────────────────────
@app.get("/api/v1/orgs/{org_id}/product-areas")
def list_areas(org_id: str, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    rows = conn.execute("SELECT * FROM product_areas WHERE org_id = ? ORDER BY created_at", (org_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/v1/orgs/{org_id}/product-areas")
def create_area(org_id: str, body: ProductAreaIn, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    pid = str(uuid.uuid4())
    conn.execute("INSERT INTO product_areas (id, org_id, name, description) VALUES (?, ?, ?, ?)", (pid, org_id, body.name, body.description))
    conn.commit(); conn.close()
    return {"id": pid, "org_id": org_id, "name": body.name, "description": body.description}


@app.delete("/api/v1/orgs/{org_id}/product-areas/{area_id}")
def delete_area(org_id: str, area_id: str, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    conn.execute("DELETE FROM product_areas WHERE id = ? AND org_id = ?", (area_id, org_id))
    conn.commit(); conn.close()
    return {"ok": True}


# ─── Competitors ─────────────────────────────────────────────────────────────
@app.get("/api/v1/orgs/{org_id}/competitors")
def list_competitors(org_id: str, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    rows = conn.execute("SELECT * FROM competitors WHERE org_id = ? ORDER BY created_at", (org_id,)).fetchall()
    conn.close()
    return [{
        "id": r["id"], "name": r["name"], "slug": r["slug"],
        "website_url": r["website_url"], "description": r["description"],
        "is_active": bool(r["is_active"]), "has_analysis": bool(r["analysis_json"]),
        "analysis_at": r["analysis_at"],
    } for r in rows]


@app.post("/api/v1/orgs/{org_id}/competitors")
def create_competitor(org_id: str, body: CompetitorIn, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    cid = str(uuid.uuid4())
    slug = body.name.lower().replace(" ", "-")[:100]
    conn.execute("INSERT INTO competitors (id, org_id, name, slug, website_url, description) VALUES (?, ?, ?, ?, ?, ?)",
                 (cid, org_id, body.name, slug, body.website_url, body.description))
    conn.commit(); conn.close()
    return {"id": cid, "name": body.name, "slug": slug, "website_url": body.website_url,
            "description": body.description, "is_active": True, "has_analysis": False}


@app.delete("/api/v1/orgs/{org_id}/competitors/{competitor_id}")
def delete_competitor(org_id: str, competitor_id: str, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    conn.execute("DELETE FROM competitors WHERE id = ? AND org_id = ?", (competitor_id, org_id))
    conn.commit(); conn.close()
    return {"ok": True}


@app.get("/api/v1/orgs/{org_id}/competitors/{competitor_id}/analysis")
def get_analysis(org_id: str, competitor_id: str, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    r = conn.execute("SELECT analysis_json, analysis_at, name FROM competitors WHERE id = ? AND org_id = ?", (competitor_id, org_id)).fetchone()
    conn.close()
    if not r or not r["analysis_json"]:
        raise HTTPException(404, "No analysis yet")
    return {"competitor_name": r["name"], "analysis": json.loads(r["analysis_json"]), "generated_at": r["analysis_at"]}


@app.post("/api/v1/orgs/{org_id}/competitors/{competitor_id}/analyze")
def analyze_competitor(org_id: str, competitor_id: str, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    api_key = get_api_key(conn, org_id)
    if not api_key:
        conn.close(); raise HTTPException(400, "No Anthropic API key configured. Add one in Settings → API Key.")
    comp = conn.execute("SELECT * FROM competitors WHERE id = ? AND org_id = ?", (competitor_id, org_id)).fetchone()
    if not comp:
        conn.close(); raise HTTPException(404, "Competitor not found")

    ctx_org = get_org_context(conn, org_id)
    lens_block = format_lens_block(ctx_org["lens_weights"])
    system = f"""You are a strategic competitive intelligence analyst for Observatory, a consumer intelligence platform. Your job is to produce sales-ready, strategically sharp competitor analyses.

Evaluate through these weighted expert lenses:
{lens_block}

Be concrete, specific, and actionable. No generic advice. No filler."""

    user_msg = f"""Analyse this competitor for {ctx_org['org_name']}.

OUR PRODUCT:
{ctx_org['product_description']}

OUR PRODUCT AREAS:
{', '.join(ctx_org['product_areas']) or 'not specified'}

COMPETITOR:
Name: {comp['name']}
Website: {comp['website_url'] or 'not provided'}
Context: {comp['description'] or 'not provided'}

Generate a comprehensive battlecard as JSON with exactly this schema:
{{
  "overview": "2-3 sentence strategic summary of who this competitor is and why they matter",
  "strengths": ["3-5 specific, concrete strengths"],
  "weaknesses": ["3-5 specific, concrete weaknesses"],
  "differentiators": ["3-5 ways WE can differentiate against them"],
  "objections": [{{"objection": "...what a prospect might say...", "response": "...how sales should respond..."}}],
  "win_themes": ["3-4 themes that help us win deals"],
  "loss_reasons": ["3-4 common reasons deals are lost to them"],
  "pricing_posture": "1-2 sentence read on their pricing strategy",
  "lens_analysis": {{""" + ", ".join(f'"{k}": "2-3 sentences from {LENS_PERSONAS.get(k, k)} perspective"' for k in ctx_org["lens_weights"]) + """}},
  "recommended_actions": ["3-4 concrete things the product/GTM team should consider"]
}}"""

    analysis = call_claude_json(api_key, system, user_msg, max_tokens=4000, org_id=org_id)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("UPDATE competitors SET analysis_json = ?, analysis_at = ? WHERE id = ?",
                 (json.dumps(analysis), now, competitor_id))
    conn.commit(); conn.close()
    return {"competitor_name": comp["name"], "analysis": analysis, "generated_at": now}


# ─── Data Sources ────────────────────────────────────────────────────────────
@app.get("/api/v1/orgs/{org_id}/data-sources")
def list_sources(org_id: str, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    rows = conn.execute("SELECT * FROM data_sources WHERE org_id = ? ORDER BY created_at", (org_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/v1/orgs/{org_id}/data-sources")
def create_source(org_id: str, body: DataSourceIn, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    sid = str(uuid.uuid4())
    conn.execute("INSERT INTO data_sources (id, org_id, source_type, name, status) VALUES (?, ?, ?, ?, 'planned')",
                 (sid, org_id, body.source_type, body.name))
    conn.commit(); conn.close()
    return {"id": sid, "source_type": body.source_type, "name": body.name, "status": "planned"}


@app.delete("/api/v1/orgs/{org_id}/data-sources/{source_id}")
def delete_source(org_id: str, source_id: str, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    conn.execute("DELETE FROM data_sources WHERE id = ? AND org_id = ?", (source_id, org_id))
    conn.commit(); conn.close()
    return {"ok": True}


# ─── AI Generation Endpoints ─────────────────────────────────────────────────
def _get_cached(conn, org_id: str, kind: str):
    row = conn.execute(
        "SELECT payload_json, created_at FROM ai_generations WHERE org_id = ? AND kind = ? ORDER BY created_at DESC LIMIT 1",
        (org_id, kind)).fetchone()
    if row:
        return {"payload": json.loads(row["payload_json"]), "generated_at": row["created_at"]}
    return None


def _save_generation(conn, org_id: str, kind: str, payload: dict):
    conn.execute("DELETE FROM ai_generations WHERE org_id = ? AND kind = ?", (org_id, kind))
    conn.execute("INSERT INTO ai_generations (id, org_id, kind, payload_json) VALUES (?, ?, ?, ?)",
                 (str(uuid.uuid4()), org_id, kind, json.dumps(payload)))
    conn.commit()


@app.get("/api/v1/orgs/{org_id}/ai/friction-scenarios")
def get_friction_scenarios(org_id: str, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    cached = _get_cached(conn, org_id, "friction")
    conn.close()
    if not cached:
        return {"items": [], "generated_at": None}
    return {"items": cached["payload"].get("items", []), "generated_at": cached["generated_at"]}


@app.post("/api/v1/orgs/{org_id}/ai/friction-scenarios")
def generate_friction(org_id: str, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    api_key = get_api_key(conn, org_id)
    if not api_key:
        conn.close(); raise HTTPException(400, "No Anthropic API key configured. Add one in Settings.")
    ctx_org = get_org_context(conn, org_id)
    if not ctx_org["product_areas"]:
        conn.close(); raise HTTPException(400, "Add product areas first in Settings → Product.")

    intel_block = get_recent_intel(conn, org_id)
    system = f"""You are a product analyst at Observatory. You surface likely friction signals — drop-offs, rage clicks, error spikes, and funnel breaks — based on common patterns in similar products.

Be specific, quantified, and grounded. Use realistic-looking metrics that a product team would actually encounter.{intel_block}"""

    user_msg = f"""Product context:
{ctx_org['product_description']}

Product areas: {', '.join(ctx_org['product_areas'])}

Based on common friction patterns for this type of product, propose 5-7 plausible friction signals the team should investigate. Return JSON:
{{
  "items": [
    {{
      "signal_type": "drop_off | rage_click | error_spike | slow_load | dead_click",
      "severity": "critical | high | medium | low",
      "product_area": "one of the areas above",
      "funnel_step": "the specific step where friction happens",
      "description": "concrete 1-2 sentence description of what's happening",
      "hypothesis": "why this is likely happening",
      "affected_users_estimate": "order-of-magnitude estimate like 'hundreds' or 'thousands'",
      "investigation_next_step": "specific action to verify this"
    }}
  ]
}}"""

    result = call_claude_json(api_key, system, user_msg, org_id=org_id)
    _save_generation(conn, org_id, "friction", result)
    conn.close()
    return {"items": result.get("items", []), "generated_at": datetime.now(timezone.utc).isoformat()}


@app.get("/api/v1/orgs/{org_id}/ai/experiment-ideas")
def get_experiment_ideas(org_id: str, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    cached = _get_cached(conn, org_id, "experiments")
    conn.close()
    if not cached:
        return {"items": [], "generated_at": None}
    return {"items": cached["payload"].get("items", []), "generated_at": cached["generated_at"]}


@app.post("/api/v1/orgs/{org_id}/ai/experiment-ideas")
def generate_experiments(org_id: str, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    api_key = get_api_key(conn, org_id)
    if not api_key:
        conn.close(); raise HTTPException(400, "No Anthropic API key configured.")
    ctx_org = get_org_context(conn, org_id)

    lens_block = format_lens_block(ctx_org["lens_weights"])
    intel_block = get_recent_intel(conn, org_id)
    system = f"""You are an experimentation strategist at Observatory. Evaluate every experiment through these weighted expert lenses:
{lens_block}

Be rigorous. Prefer experiments with clear hypotheses and measurable outcomes.{intel_block}"""

    user_msg = f"""Product:
{ctx_org['product_description']}

Product areas: {', '.join(ctx_org['product_areas']) or 'not specified'}
Competitors tracked: {', '.join([c['name'] for c in ctx_org['competitors']]) or 'none'}

Generate 4-6 prioritised experiment recommendations. Return JSON:
{{
  "items": [
    {{
      "title": "concise experiment name",
      "hypothesis": "If we do X, then Y because Z",
      "product_area": "which area",
      "expected_impact": "high | medium | low",
      "effort_estimate": "small | medium | large",
      "confidence": 0.XX,
      "success_metric": "the one metric that matters",
      "lens_analysis": {""" + ", ".join(f'"{k}": "1-2 sentences from {LENS_PERSONAS.get(k, k)} perspective"' for k in ctx_org["lens_weights"]) + """}
    }}
  ]
}}"""

    result = call_claude_json(api_key, system, user_msg, org_id=org_id)
    _save_generation(conn, org_id, "experiments", result)
    conn.close()
    return {"items": result.get("items", []), "generated_at": datetime.now(timezone.utc).isoformat()}


@app.post("/api/v1/orgs/{org_id}/ai/ask")
def ask_claude(org_id: str, body: AskIn, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    api_key = get_api_key(conn, org_id)
    if not api_key:
        conn.close(); raise HTTPException(400, "No Anthropic API key configured.")
    ctx_org = get_org_context(conn, org_id)
    conn.close()

    lens_block = format_lens_block(ctx_org["lens_weights"])
    system = f"""You are the Observatory strategic advisor for {ctx_org['org_name']}. You help product teams make better decisions using the context they've configured.

PRODUCT: {ctx_org['product_description']}
PRODUCT AREAS: {', '.join(ctx_org['product_areas']) or 'not specified'}
COMPETITORS: {', '.join([c['name'] for c in ctx_org['competitors']]) or 'none tracked'}

EXPERT LENSES (weigh your answer proportionally):
{lens_block}

Answer crisply, concretely, with an opinion. When appropriate, structure your answer through the configured expert lenses. Keep answers under 300 words unless complexity demands more."""

    answer = call_claude(api_key, system, body.question, max_tokens=1500, org_id=org_id)
    return {"answer": answer, "generated_at": datetime.now(timezone.utc).isoformat()}


@app.get("/api/v1/orgs/{org_id}/ai/summary")
def ai_summary(org_id: str, ctx: tuple[str, str] = Depends(require_org)):
    """Returns counts of AI-generated artifacts for the overview."""
    check_org(org_id, ctx)
    conn = get_db()
    friction = _get_cached(conn, org_id, "friction")
    exp = _get_cached(conn, org_id, "experiments")
    analyzed = conn.execute("SELECT COUNT(*) c FROM competitors WHERE org_id = ? AND analysis_json IS NOT NULL", (org_id,)).fetchone()["c"]
    total_comps = conn.execute("SELECT COUNT(*) c FROM competitors WHERE org_id = ?", (org_id,)).fetchone()["c"]
    api_key = get_api_key(conn, org_id)
    firecrawl_key = get_firecrawl_key(conn, org_id)
    perplexity_key = get_perplexity_key(conn, org_id)
    intel_count = conn.execute("SELECT COUNT(*) c FROM intelligence_feeds WHERE org_id = ?", (org_id,)).fetchone()["c"]
    conn.close()
    return {
        "has_api_key": api_key is not None,
        "has_firecrawl_key": firecrawl_key is not None,
        "has_perplexity_key": perplexity_key is not None,
        "friction_count": len((friction or {}).get("payload", {}).get("items", [])) if friction else 0,
        "friction_at": friction["generated_at"] if friction else None,
        "experiments_count": len((exp or {}).get("payload", {}).get("items", [])) if exp else 0,
        "experiments_at": exp["generated_at"] if exp else None,
        "competitors_analyzed": analyzed,
        "competitors_total": total_comps,
        "intel_feeds_count": intel_count,
    }


# ─── Insights (Claude synthesis) ────────────────────────────────────────────
@app.get("/api/v1/orgs/{org_id}/ai/insights")
def get_insights(org_id: str, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    cached = _get_cached(conn, org_id, "insights")
    conn.close()
    if not cached:
        return {"items": [], "generated_at": None}
    return {"items": cached["payload"].get("items", []), "generated_at": cached["generated_at"]}


@app.post("/api/v1/orgs/{org_id}/ai/insights")
def generate_insights(org_id: str, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    api_key = get_api_key(conn, org_id)
    if not api_key:
        conn.close(); raise HTTPException(400, "No Anthropic API key configured.")
    ctx_org = get_org_context(conn, org_id)
    # Gather existing AI artifacts for synthesis
    friction_cached = _get_cached(conn, org_id, "friction")
    exp_cached = _get_cached(conn, org_id, "experiments")
    analyses = conn.execute(
        "SELECT name, analysis_json FROM competitors WHERE org_id = ? AND analysis_json IS NOT NULL", (org_id,)
    ).fetchall()

    existing_intel = []
    if friction_cached:
        existing_intel.append(f"FRICTION SCENARIOS:\n{json.dumps(friction_cached['payload'].get('items', [])[:3], indent=1)}")
    if exp_cached:
        existing_intel.append(f"EXPERIMENT IDEAS:\n{json.dumps(exp_cached['payload'].get('items', [])[:3], indent=1)}")
    for a in analyses[:3]:
        existing_intel.append(f"COMPETITOR ANALYSIS ({a['name']}):\n{a['analysis_json'][:500]}")

    intel_block = get_recent_intel(conn, org_id)
    lens_block = format_lens_block(ctx_org["lens_weights"])
    system = f"""You are a senior product strategist at Observatory. You synthesize cross-cutting insights from multiple intelligence streams.

EXPERT LENSES:
{lens_block}

Be concrete, specific, and surprising. Surface patterns the team wouldn't see by looking at each signal stream in isolation.{intel_block}"""

    user_msg = f"""Product: {ctx_org['product_description']}
Product areas: {', '.join(ctx_org['product_areas']) or 'not specified'}
Competitors: {', '.join([c['name'] for c in ctx_org['competitors']]) or 'none'}

EXISTING INTELLIGENCE:
{chr(10).join(existing_intel) or 'No intelligence generated yet — synthesize from product context alone.'}

Synthesize 4-6 cross-cutting insights. Return JSON:
{{
  "items": [
    {{
      "title": "concise insight title",
      "summary": "1-2 sentence key finding",
      "detail": "2-3 sentences of supporting evidence and reasoning",
      "category": "opportunity | risk | trend",
      "related_areas": ["relevant product areas"],
      "confidence": 0.XX,
      "lens_analysis": {{{", ".join(f'"{k}": "1 sentence from this lens"' for k in ctx_org["lens_weights"])}}}
    }}
  ]
}}"""

    result = call_claude_json(api_key, system, user_msg, org_id=org_id)
    _save_generation(conn, org_id, "insights", result)
    conn.close()
    return {"items": result.get("items", []), "generated_at": datetime.now(timezone.utc).isoformat()}


# ─── Research gaps (Claude) ────────────────────────────────────────────────
@app.get("/api/v1/orgs/{org_id}/ai/research-gaps")
def get_research_gaps(org_id: str, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    cached = _get_cached(conn, org_id, "research")
    conn.close()
    if not cached:
        return {"items": [], "generated_at": None}
    return {"items": cached["payload"].get("items", []), "generated_at": cached["generated_at"]}


@app.post("/api/v1/orgs/{org_id}/ai/research-gaps")
def generate_research_gaps(org_id: str, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    api_key = get_api_key(conn, org_id)
    if not api_key:
        conn.close(); raise HTTPException(400, "No Anthropic API key configured.")
    ctx_org = get_org_context(conn, org_id)
    # Gather all existing intelligence
    all_kinds = ["friction", "experiments", "insights"]
    intel_summary = []
    for kind in all_kinds:
        cached = _get_cached(conn, org_id, kind)
        if cached:
            items = cached["payload"].get("items", [])
            intel_summary.append(f"{kind.upper()}: {len(items)} items generated")

    intel_block = get_recent_intel(conn, org_id)
    lens_block = format_lens_block(ctx_org["lens_weights"])
    system = f"""You are a research director at Observatory. You identify knowledge gaps — things the team would need to know to make confident decisions but currently lacks evidence for. You then produce structured research briefs that can be directly commissioned.

EXPERT LENSES:
{lens_block}

Be specific about methodology, realistic about costs, and honest about expected value.{intel_block}"""

    user_msg = f"""Product: {ctx_org['product_description']}
Product areas: {', '.join(ctx_org['product_areas']) or 'not specified'}
Competitors: {', '.join([c['name'] for c in ctx_org['competitors']]) or 'none'}

EXISTING INTELLIGENCE: {'; '.join(intel_summary) or 'None generated yet.'}

Identify 3-5 knowledge gaps and produce a research brief for each. Return JSON:
{{
  "items": [
    {{
      "title": "brief title",
      "knowledge_gap": "what we don't know and why it matters",
      "objective": "what this research would answer",
      "methodology": "survey | interview | usability test | diary study | A/B test | desk research",
      "sample_size": "e.g. 15-20 participants",
      "cost_estimate": "e.g. $2,000-5,000",
      "timeline": "e.g. 2-3 weeks",
      "expected_value": "what decisions this unlocks",
      "priority": "high | medium | low",
      "related_area": "product area"
    }}
  ]
}}"""

    result = call_claude_json(api_key, system, user_msg, org_id=org_id)
    _save_generation(conn, org_id, "research", result)
    conn.close()
    return {"items": result.get("items", []), "generated_at": datetime.now(timezone.utc).isoformat()}


# ─── Digest (Claude) ──────────────────────────────────────────────────────
@app.get("/api/v1/orgs/{org_id}/ai/digest")
def get_digest(org_id: str, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    cached = _get_cached(conn, org_id, "digest")
    conn.close()
    if not cached:
        return {"digest": None, "generated_at": None}
    return {"digest": cached["payload"], "generated_at": cached["generated_at"]}


@app.post("/api/v1/orgs/{org_id}/ai/digest")
def generate_digest(org_id: str, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    api_key = get_api_key(conn, org_id)
    if not api_key:
        conn.close(); raise HTTPException(400, "No Anthropic API key configured.")
    ctx_org = get_org_context(conn, org_id)
    # Gather all intelligence
    all_intel = {}
    for kind in ["friction", "experiments", "insights", "research"]:
        cached = _get_cached(conn, org_id, kind)
        if cached:
            all_intel[kind] = cached["payload"].get("items", [])
    analyses = conn.execute(
        "SELECT name, analysis_json FROM competitors WHERE org_id = ? AND analysis_json IS NOT NULL", (org_id,)
    ).fetchall()
    comp_summaries = []
    for a in analyses:
        try:
            parsed = json.loads(a["analysis_json"])
            comp_summaries.append(f"- {a['name']}: {parsed.get('overview', '')[:200]}")
        except Exception:
            pass

    intel_block = get_recent_intel(conn, org_id)
    lens_block = format_lens_block(ctx_org["lens_weights"])
    system = f"""You are the Observatory weekly briefing editor for {ctx_org['org_name']}. Produce a crisp, scannable executive digest.

EXPERT LENSES:
{lens_block}{intel_block}"""

    user_msg = f"""Product: {ctx_org['product_description']}

INTELLIGENCE AVAILABLE:
- Friction scenarios: {len(all_intel.get('friction', []))} items
- Experiment ideas: {len(all_intel.get('experiments', []))} items
- Insights: {len(all_intel.get('insights', []))} items
- Research briefs: {len(all_intel.get('research', []))} items
- Competitor analyses: {len(comp_summaries)}

{chr(10).join(comp_summaries) if comp_summaries else ''}

Produce a structured digest. Return JSON:
{{
  "title": "Weekly Intelligence Digest — {ctx_org['org_name']}",
  "tldr": "3-4 sentence executive summary of the most important things to know",
  "sections": {{
    "competitive": "2-3 paragraphs on competitive landscape",
    "friction": "2-3 paragraphs on friction and user experience signals",
    "experiments": "2-3 paragraphs on experiment recommendations and priorities",
    "research": "1-2 paragraphs on knowledge gaps and recommended research"
  }},
  "top_actions": ["3-5 specific recommended actions for this week"]
}}"""

    result = call_claude_json(api_key, system, user_msg, max_tokens=4000, org_id=org_id)
    _save_generation(conn, org_id, "digest", result)
    conn.close()
    return {"digest": result, "generated_at": datetime.now(timezone.utc).isoformat()}


# ─── Knowledge upload (functional) ────────────────────────────────────────
@app.get("/api/v1/orgs/{org_id}/knowledge")
def list_knowledge(org_id: str, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    # Create table if missing (migration)
    conn.execute("""CREATE TABLE IF NOT EXISTS knowledge_documents (
        id TEXT PRIMARY KEY, org_id TEXT NOT NULL, title TEXT NOT NULL,
        doc_type TEXT, file_name TEXT, file_size INTEGER,
        status TEXT DEFAULT 'uploaded', created_at TEXT DEFAULT (datetime('now'))
    )""")
    conn.commit()
    rows = conn.execute("SELECT * FROM knowledge_documents WHERE org_id = ? ORDER BY created_at DESC", (org_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/v1/orgs/{org_id}/knowledge/upload")
async def upload_knowledge(org_id: str, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    from fastapi import Request
    # For now, record metadata without actual file processing
    conn = get_db()
    conn.execute("""CREATE TABLE IF NOT EXISTS knowledge_documents (
        id TEXT PRIMARY KEY, org_id TEXT NOT NULL, title TEXT NOT NULL,
        doc_type TEXT, file_name TEXT, file_size INTEGER,
        status TEXT DEFAULT 'uploaded', created_at TEXT DEFAULT (datetime('now'))
    )""")
    doc_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO knowledge_documents (id, org_id, title, doc_type, status) VALUES (?, ?, ?, ?, 'uploaded')",
        (doc_id, org_id, f"Document {doc_id[:8]}", "research", )
    )
    conn.commit(); conn.close()
    return {"id": doc_id, "title": f"Document {doc_id[:8]}", "doc_type": "research", "status": "uploaded"}


# ─── Legacy intelligence endpoints (empty — deprecated) ──────────────────────
@app.get("/api/v1/orgs/{org_id}/friction-reports")
def friction_list(org_id: str, severity: str | None = None, status: str | None = None, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx); return {"items": [], "total": 0}


@app.get("/api/v1/orgs/{org_id}/insights")
def insights_list(org_id: str, insight_type: str | None = None, status: str | None = None, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx); return {"items": [], "total": 0}


@app.get("/api/v1/orgs/{org_id}/scores/priorities")
def scores_priorities(org_id: str, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx); return []


@app.get("/api/v1/orgs/{org_id}/scores/experiments")
def scores_experiments(org_id: str, ctx: tuple[str, str] = Depends(require_org)):
    return []


@app.get("/api/v1/orgs/{org_id}/knowledge")
def knowledge_list(org_id: str, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx); return []


@app.post("/api/v1/orgs/{org_id}/knowledge/upload")
def knowledge_upload(org_id: str, ctx: tuple[str, str] = Depends(require_org)):
    return {"id": str(uuid.uuid4()), "title": "Uploaded Document", "doc_type": "research",
            "file_type": "pdf", "summary": None, "key_findings": {}, "chunk_count": 0, "status": "processing"}


@app.post("/api/v1/orgs/{org_id}/knowledge/search")
def knowledge_search(org_id: str, ctx: tuple[str, str] = Depends(require_org)):
    return []


@app.get("/api/v1/orgs/{org_id}/digests")
def digests_list(org_id: str, ctx: tuple[str, str] = Depends(require_org)):
    return []


@app.get("/api/v1/research/briefs")
def research_briefs(_=Depends(get_user)):
    return []


@app.post("/api/v1/research/detect-gaps")
def research_detect_gaps(_=Depends(get_user)):
    return {"gaps": [], "count": 0}


# ─── Intelligence Gathering ─────────────────────────────────────────────────

def _resolve_competitor_url(conn, org_id: str, competitor_id: str | None, url: str | None) -> tuple:
    """Resolve a competitor_id or url into (competitor_row_or_None, url)."""
    if competitor_id:
        comp = conn.execute("SELECT * FROM competitors WHERE id = ? AND org_id = ?", (competitor_id, org_id)).fetchone()
        if not comp:
            raise HTTPException(404, "Competitor not found")
        return comp, url or comp["website_url"]
    if url:
        return None, url
    raise HTTPException(400, "Provide competitor_id or url")


@app.post("/api/v1/orgs/{org_id}/intel/scrape-competitor")
def intel_scrape_competitor(org_id: str, body: IntelScrapeIn, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    api_key = get_firecrawl_key(conn, org_id)
    if not api_key:
        conn.close()
        raise HTTPException(400, "No Firecrawl API key configured. Add one in Settings or set FIRECRAWL_API_KEY env var.")
    comp, target_url = _resolve_competitor_url(conn, org_id, body.competitor_id, body.url)
    if not target_url:
        conn.close()
        raise HTTPException(400, "No URL available for this competitor")
    try:
        result = firecrawl_scrape(api_key, target_url, org_id=org_id)
    except HTTPException:
        conn.close(); raise
    except httpx.HTTPStatusError as e:
        conn.close()
        raise HTTPException(e.response.status_code, f"Firecrawl error: {e.response.text[:500]}")
    except Exception as e:
        conn.close()
        raise HTTPException(502, f"Firecrawl request failed: {str(e)}")
    feed_id = save_intel_feed(conn, org_id, "firecrawl", target_url, result)
    conn.close()
    return {"feed_id": feed_id, "source": "firecrawl", "url": target_url, "result": result}


@app.post("/api/v1/orgs/{org_id}/intel/crawl-competitor")
def intel_crawl_competitor(org_id: str, body: IntelCrawlIn, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    api_key = get_firecrawl_key(conn, org_id)
    if not api_key:
        conn.close()
        raise HTTPException(400, "No Firecrawl API key configured.")
    comp, target_url = _resolve_competitor_url(conn, org_id, body.competitor_id, body.url)
    if not target_url:
        conn.close()
        raise HTTPException(400, "No URL available for this competitor")
    try:
        result = firecrawl_crawl(api_key, target_url, body.max_pages or 10, org_id=org_id)
    except HTTPException:
        conn.close(); raise
    except httpx.HTTPStatusError as e:
        conn.close()
        raise HTTPException(e.response.status_code, f"Firecrawl error: {e.response.text[:500]}")
    except Exception as e:
        conn.close()
        raise HTTPException(502, f"Firecrawl crawl failed: {str(e)}")
    feed_id = save_intel_feed(conn, org_id, "firecrawl", f"crawl:{target_url}", result)
    conn.close()
    return {"feed_id": feed_id, "source": "firecrawl", "url": target_url, "result": result}


@app.post("/api/v1/orgs/{org_id}/intel/web-search")
def intel_web_search(org_id: str, body: IntelWebSearchIn, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    api_key = get_perplexity_key(conn, org_id)
    if not api_key:
        conn.close()
        raise HTTPException(400, "No Perplexity API key configured. Add one in Settings or set PERPLEXITY_API_KEY env var.")
    try:
        result = perplexity_search(api_key, body.query, org_id=org_id)
    except HTTPException:
        conn.close(); raise
    except httpx.HTTPStatusError as e:
        conn.close()
        raise HTTPException(e.response.status_code, f"Perplexity error: {e.response.text[:500]}")
    except Exception as e:
        conn.close()
        raise HTTPException(502, f"Perplexity request failed: {str(e)}")
    feed_id = save_intel_feed(conn, org_id, "perplexity", body.query, result)
    conn.close()
    return {"feed_id": feed_id, "source": "perplexity", "query": body.query, "result": result}


@app.post("/api/v1/orgs/{org_id}/intel/competitor-news")
def intel_competitor_news(org_id: str, body: IntelCompetitorNewsIn, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    api_key = get_perplexity_key(conn, org_id)
    if not api_key:
        conn.close()
        raise HTTPException(400, "No Perplexity API key configured.")
    comp = conn.execute("SELECT * FROM competitors WHERE id = ? AND org_id = ?", (body.competitor_id, org_id)).fetchone()
    if not comp:
        conn.close()
        raise HTTPException(404, "Competitor not found")
    now = datetime.now(timezone.utc)
    query = f"latest news about {comp['name']} {now.strftime('%B')} {now.year}"
    try:
        result = perplexity_search(api_key, query, org_id=org_id)
    except HTTPException:
        conn.close(); raise
    except httpx.HTTPStatusError as e:
        conn.close()
        raise HTTPException(e.response.status_code, f"Perplexity error: {e.response.text[:500]}")
    except Exception as e:
        conn.close()
        raise HTTPException(502, f"Perplexity request failed: {str(e)}")
    feed_id = save_intel_feed(conn, org_id, "perplexity", query, result)
    conn.close()
    return {"feed_id": feed_id, "source": "perplexity", "competitor": comp["name"], "query": query, "result": result}


@app.post("/api/v1/orgs/{org_id}/intel/hackernews-scan")
def intel_hackernews_scan(org_id: str, body: IntelHNScanIn, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    query = body.query
    if not query:
        comps = conn.execute("SELECT name FROM competitors WHERE org_id = ?", (org_id,)).fetchall()
        query = " OR ".join(c["name"] for c in comps) if comps else ""
    if not query:
        conn.close()
        raise HTTPException(400, "No query provided and no competitors configured")
    try:
        hits = hackernews_search(query, org_id=org_id)
    except Exception as e:
        conn.close()
        raise HTTPException(502, f"HackerNews search failed: {str(e)}")
    result = {"query": query, "hits": hits}
    feed_id = save_intel_feed(conn, org_id, "hackernews", query, result)
    conn.close()
    return {"feed_id": feed_id, "source": "hackernews", "query": query, "hits": hits}


@app.post("/api/v1/orgs/{org_id}/intel/reddit-scan")
def intel_reddit_scan(org_id: str, body: IntelRedditScanIn, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    query = body.query
    if not query:
        comps = conn.execute("SELECT name FROM competitors WHERE org_id = ?", (org_id,)).fetchall()
        query = " OR ".join(c["name"] for c in comps) if comps else ""
    if not query:
        conn.close()
        raise HTTPException(400, "No query provided and no competitors configured")
    try:
        posts = reddit_search(query, body.subreddit, org_id=org_id)
    except Exception as e:
        conn.close()
        raise HTTPException(502, f"Reddit search failed: {str(e)}")
    result = {"query": query, "subreddit": body.subreddit, "posts": posts}
    feed_id = save_intel_feed(conn, org_id, "reddit", query, result)
    conn.close()
    return {"feed_id": feed_id, "source": "reddit", "query": query, "posts": posts}


@app.post("/api/v1/orgs/{org_id}/intel/scan-reviews")
def intel_scan_reviews(org_id: str, body: IntelReviewScanIn, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    api_key = get_perplexity_key(conn, org_id)
    if not api_key:
        conn.close()
        raise HTTPException(400, "No Perplexity API key configured.")
    comp = conn.execute("SELECT * FROM competitors WHERE id = ? AND org_id = ?", (body.competitor_id, org_id)).fetchone()
    if not comp:
        conn.close()
        raise HTTPException(404, "Competitor not found")
    platform = body.platform or "G2 Capterra Trustpilot"
    query = f"{comp['name']} reviews {platform} 2024 2025 — summarize key themes, pros, cons, and ratings"
    try:
        result = perplexity_search(api_key, query, org_id=org_id)
    except HTTPException:
        conn.close(); raise
    except httpx.HTTPStatusError as e:
        conn.close()
        raise HTTPException(e.response.status_code, f"Perplexity error: {e.response.text[:500]}")
    except Exception as e:
        conn.close()
        raise HTTPException(502, f"Perplexity request failed: {str(e)}")
    feed_id = save_intel_feed(conn, org_id, "g2_reviews", query, result)
    conn.close()
    return {"feed_id": feed_id, "source": "g2_reviews", "competitor": comp["name"], "query": query, "result": result}


@app.post("/api/v1/orgs/{org_id}/intel/academic-search")
def intel_academic_search(org_id: str, body: IntelAcademicIn, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    serpapi_key = os.environ.get("SERPAPI_KEY")
    if serpapi_key:
        ok, reason = guard_serpapi(org_id)
        if not ok:
            conn.close()
            raise HTTPException(429, f"Cost limit reached: {reason}")
        try:
            r = httpx.get("https://serpapi.com/search",
                          params={"engine": "google_scholar", "q": body.query, "api_key": serpapi_key},
                          timeout=15.0)
            r.raise_for_status()
            result = r.json()
            log_serpapi_usage(org_id, "academic_search")
        except HTTPException:
            conn.close(); raise
        except Exception as e:
            conn.close()
            raise HTTPException(502, f"SerpAPI request failed: {str(e)}")
        feed_id = save_intel_feed(conn, org_id, "google_scholar", body.query, result)
        conn.close()
        return {"feed_id": feed_id, "source": "google_scholar", "query": body.query, "result": result}
    # Fallback to Perplexity
    pplx_key = get_perplexity_key(conn, org_id)
    if not pplx_key:
        conn.close()
        raise HTTPException(400, "No SERPAPI_KEY env var and no Perplexity API key configured.")
    query = f"academic research papers about: {body.query} — cite recent peer-reviewed studies"
    try:
        result = perplexity_search(pplx_key, query, org_id=org_id)
    except HTTPException:
        conn.close(); raise
    except Exception as e:
        conn.close()
        raise HTTPException(502, f"Perplexity request failed: {str(e)}")
    feed_id = save_intel_feed(conn, org_id, "google_scholar", body.query, result)
    conn.close()
    return {"feed_id": feed_id, "source": "google_scholar_via_perplexity", "query": body.query, "result": result}


@app.get("/api/v1/orgs/{org_id}/intel/feeds")
def intel_feeds_list(org_id: str, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    rows = conn.execute(
        "SELECT id, source, query, result_json, created_at FROM intelligence_feeds WHERE org_id = ? ORDER BY created_at DESC LIMIT 50",
        (org_id,)
    ).fetchall()
    conn.close()
    return [{"id": r["id"], "source": r["source"], "query": r["query"], "content": r["result_json"], "created_at": r["created_at"]} for r in rows]


@app.get("/api/v1/orgs/{org_id}/intel/feeds/{feed_id}")
def intel_feed_detail(org_id: str, feed_id: str, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM intelligence_feeds WHERE id = ? AND org_id = ?", (feed_id, org_id)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Feed not found")
    return {**dict(row), "result_json": json.loads(row["result_json"])}


@app.post("/api/v1/orgs/{org_id}/api-keys/firecrawl")
def set_firecrawl_key(org_id: str, body: IntelApiKeyIn, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    conn.execute("UPDATE organizations SET firecrawl_api_key = ? WHERE id = ?", (body.api_key, org_id))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.post("/api/v1/orgs/{org_id}/api-keys/perplexity")
def set_perplexity_key(org_id: str, body: IntelApiKeyIn, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    conn.execute("UPDATE organizations SET perplexity_api_key = ? WHERE id = ?", (body.api_key, org_id))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.post("/api/v1/orgs/{org_id}/ai/deep-analysis")
def ai_deep_analysis(org_id: str, body: IntelDeepAnalysisIn, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    comp = conn.execute("SELECT * FROM competitors WHERE id = ? AND org_id = ?", (body.competitor_id, org_id)).fetchone()
    if not comp:
        conn.close()
        raise HTTPException(404, "Competitor not found")

    claude_key = get_api_key(conn, org_id)
    if not claude_key:
        conn.close()
        raise HTTPException(400, "No Anthropic API key configured.")

    intel_sections = []

    # Firecrawl scrape (optional)
    fc_key = get_firecrawl_key(conn, org_id)
    if fc_key and comp["website_url"]:
        try:
            scrape = firecrawl_scrape(fc_key, comp["website_url"], org_id=org_id)
            save_intel_feed(conn, org_id, "firecrawl", comp["website_url"], scrape)
            md = scrape.get("data", {}).get("markdown", "")
            if md:
                intel_sections.append(f"## WEBSITE CONTENT (scraped)\n{md[:4000]}")
        except Exception:
            pass

    # Perplexity news (optional)
    pplx_key = get_perplexity_key(conn, org_id)
    if pplx_key:
        now = datetime.now(timezone.utc)
        news_query = f"latest news about {comp['name']} {now.strftime('%B')} {now.year}"
        try:
            news = perplexity_search(pplx_key, news_query, org_id=org_id)
            save_intel_feed(conn, org_id, "perplexity", news_query, news)
            answer = news.get("choices", [{}])[0].get("message", {}).get("content", "")
            if answer:
                intel_sections.append(f"## RECENT NEWS (from web search)\n{answer[:3000]}")
        except Exception:
            pass

    # HackerNews (always free)
    try:
        hn_hits = hackernews_search(comp["name"], org_id=org_id)
        if hn_hits:
            save_intel_feed(conn, org_id, "hackernews", comp["name"], {"hits": hn_hits})
            hn_text = "\n".join(f"- {h.get('title','')} ({h.get('points',0)} pts, {h.get('num_comments',0)} comments)" for h in hn_hits[:10])
            intel_sections.append(f"## HACKERNEWS MENTIONS\n{hn_text}")
    except Exception:
        pass

    # Reddit (always free)
    try:
        reddit_posts = reddit_search(comp["name"], org_id=org_id)
        if reddit_posts:
            save_intel_feed(conn, org_id, "reddit", comp["name"], {"posts": reddit_posts})
            rd_text = "\n".join(f"- r/{p.get('subreddit','')} — {p.get('title','')} ({p.get('score',0)} upvotes)" for p in reddit_posts[:10])
            intel_sections.append(f"## REDDIT MENTIONS\n{rd_text}")
    except Exception:
        pass

    ctx_org = get_org_context(conn, org_id)
    lens_block = format_lens_block(ctx_org["lens_weights"])
    intel_block = "\n\n".join(intel_sections) if intel_sections else "No external intelligence could be gathered."

    system = f"""You are an elite competitive intelligence analyst for Observatory. You have access to REAL gathered intelligence about this competitor. Use it to produce the most accurate, data-backed analysis possible.

Evaluate through these weighted expert lenses:
{lens_block}

Be concrete, specific, and grounded in the actual intelligence provided."""

    user_msg = f"""Deep analysis of {comp['name']} for {ctx_org['org_name']}.

OUR PRODUCT: {ctx_org['product_description']}
OUR PRODUCT AREAS: {', '.join(ctx_org['product_areas']) or 'not specified'}

COMPETITOR:
Name: {comp['name']}
Website: {comp['website_url'] or 'not provided'}
Context: {comp['description'] or 'not provided'}

GATHERED INTELLIGENCE:
{intel_block}

Generate a comprehensive deep-analysis battlecard as JSON:
{{
  "overview": "3-4 sentence strategic summary grounded in real data",
  "strengths": ["5-7 specific strengths backed by evidence"],
  "weaknesses": ["5-7 specific weaknesses backed by evidence"],
  "differentiators": ["5-7 ways WE can differentiate"],
  "objections": [{{"objection": "...", "response": "..."}}],
  "win_themes": ["4-5 themes"],
  "loss_reasons": ["4-5 reasons"],
  "pricing_posture": "pricing analysis",
  "market_sentiment": "summary of how the market/community perceives this competitor based on HN, Reddit, reviews",
  "recent_developments": "summary of recent news and changes",
  "lens_analysis": {{""" + ", ".join(f'"{k}": "analysis from {LENS_PERSONAS.get(k, k)} perspective"' for k in ctx_org["lens_weights"]) + """}},
  "recommended_actions": ["5-7 concrete actions"],
  "intelligence_sources_used": ["list of sources that provided data"]
}}"""

    analysis = call_claude_json(claude_key, system, user_msg, max_tokens=6000, org_id=org_id)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("UPDATE competitors SET analysis_json = ?, analysis_at = ? WHERE id = ?",
                 (json.dumps(analysis), now, body.competitor_id))
    # Also save as ai_generation
    conn.execute("INSERT INTO ai_generations (id, org_id, kind, payload_json) VALUES (?, ?, 'deep_analysis', ?)",
                 (str(uuid.uuid4()), org_id, json.dumps({"competitor_id": body.competitor_id, "analysis": analysis})))
    conn.commit()
    conn.close()
    return {"competitor_name": comp["name"], "analysis": analysis, "generated_at": now, "intel_sources": len(intel_sections)}


# ─── Chat endpoints ─────────────────────────────────────────────────────────
class ChatMessageIn(BaseModel):
    content: str


@app.get("/api/v1/orgs/{org_id}/chat/conversations")
def chat_list_conversations(org_id: str, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    user_id, _ = ctx
    conn = get_db()
    rows = conn.execute(
        "SELECT id, title, created_at, updated_at FROM chat_conversations WHERE org_id = ? AND user_id = ? ORDER BY updated_at DESC LIMIT 50",
        (org_id, user_id)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/v1/orgs/{org_id}/chat/conversations")
def chat_create_conversation(org_id: str, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    user_id, _ = ctx
    conv_id = str(uuid.uuid4())
    conn = get_db()
    conn.execute(
        "INSERT INTO chat_conversations (id, org_id, user_id) VALUES (?, ?, ?)",
        (conv_id, org_id, user_id)
    )
    conn.commit()
    conn.close()
    return {"id": conv_id, "title": "New conversation"}


@app.get("/api/v1/orgs/{org_id}/chat/conversations/{conv_id}")
def chat_get_messages(org_id: str, conv_id: str, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    conv = conn.execute("SELECT * FROM chat_conversations WHERE id = ? AND org_id = ?", (conv_id, org_id)).fetchone()
    if not conv:
        conn.close()
        raise HTTPException(404, "Conversation not found")
    msgs = conn.execute(
        "SELECT id, role, content, tool_calls_json, created_at FROM chat_messages WHERE conversation_id = ? ORDER BY created_at ASC",
        (conv_id,)
    ).fetchall()
    conn.close()
    return {"id": conv["id"], "title": conv["title"], "messages": [dict(m) for m in msgs]}


@app.delete("/api/v1/orgs/{org_id}/chat/conversations/{conv_id}")
def chat_delete_conversation(org_id: str, conv_id: str, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    conn.execute("DELETE FROM chat_conversations WHERE id = ? AND org_id = ?", (conv_id, org_id))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.post("/api/v1/orgs/{org_id}/chat/conversations/{conv_id}/messages")
def chat_send_message(org_id: str, conv_id: str, body: ChatMessageIn, request: Request, ctx: tuple[str, str] = Depends(require_org)):
    check_org(org_id, ctx)
    conn = get_db()
    conv = conn.execute("SELECT * FROM chat_conversations WHERE id = ? AND org_id = ?", (conv_id, org_id)).fetchone()
    if not conv:
        conn.close()
        raise HTTPException(404, "Conversation not found")

    api_key = get_api_key(conn, org_id)
    if not api_key:
        conn.close()
        raise HTTPException(400, "No Anthropic API key configured")

    # Save user message
    user_msg_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO chat_messages (id, conversation_id, role, content) VALUES (?, ?, 'user', ?)",
        (user_msg_id, conv_id, body.content)
    )
    # Auto-title from first message
    msg_count = conn.execute("SELECT COUNT(*) c FROM chat_messages WHERE conversation_id = ?", (conv_id,)).fetchone()["c"]
    if msg_count == 1:
        title = body.content[:50] + ("..." if len(body.content) > 50 else "")
        conn.execute("UPDATE chat_conversations SET title = ? WHERE id = ?", (title, conv_id))
    conn.execute("UPDATE chat_conversations SET updated_at = datetime('now') WHERE id = ?", (conv_id,))
    conn.commit()

    # Load conversation history (last 20 messages)
    history_rows = conn.execute(
        "SELECT role, content, tool_calls_json FROM chat_messages WHERE conversation_id = ? ORDER BY created_at ASC",
        (conv_id,)
    ).fetchall()

    # Build org context for system prompt
    ctx_org = get_org_context(conn, org_id)
    conn.close()

    # Build Anthropic messages from history
    messages = []
    for row in history_rows[-20:]:
        if row["role"] == "user":
            messages.append({"role": "user", "content": row["content"]})
        elif row["role"] == "assistant":
            content = row["content"]
            tool_calls = json.loads(row["tool_calls_json"]) if row["tool_calls_json"] else None
            if tool_calls:
                # Reconstruct assistant content blocks
                blocks = []
                if content:
                    blocks.append({"type": "text", "text": content})
                for tc in tool_calls:
                    blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["input"]})
                messages.append({"role": "assistant", "content": blocks})
            else:
                messages.append({"role": "assistant", "content": content})
        elif row["role"] == "tool":
            tool_data = json.loads(row["tool_calls_json"]) if row["tool_calls_json"] else {}
            messages.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_data.get("tool_use_id", ""), "content": row["content"]}]})

    # Build CCO system prompt
    from agent_runner import TOOLS as AGENT_TOOLS, execute_tool as agent_execute_tool
    from specialists import SPECIALISTS, build_specialist_prompt, get_specialist_tools

    lens_block = format_lens_block(ctx_org["lens_weights"])
    system = f"""You are the Chief Consumer Officer (CCO) for {ctx_org['org_name']}, powered by Observatory — a consumer intelligence platform.

You lead a team of specialist analysts. Your role is to:
1. Understand the user's question and determine which specialist perspective(s) apply
2. Consult relevant specialists using the consult_specialist tool
3. Synthesize their analyses into unified, actionable recommendations
4. Highlight where specialists agree, disagree, or see different priorities
5. Make a clear recommendation with your rationale

YOUR SPECIALIST TEAM:
- **Behavioural Scientist** — biases, nudges, habit loops, persuasion frameworks (Cialdini, Kahneman, BJ Fogg)
- **Consumer Researcher** — mixed methods, segmentation, journey mapping, voice of customer
- **Clinical Psychologist** — evidence-based practice, diagnostic frameworks, ethical design, user wellbeing
- **Qualitative Specialist** — thematic analysis, ethnography, diary studies, lived experience
- **Data Scientist** — causal inference, A/B testing, Bayesian methods, statistical rigour
- **Clinical Lead** — systematic review, GRADE framework, research governance, methodology quality
- **UX Researcher** — Nielsen heuristics, Baymard benchmarks, accessibility, task analysis
- **Business Strategist** — competitive strategy, Porter's forces, pricing, market positioning, unit economics

DELEGATION RULES:
- For analytical questions: ALWAYS consult 2-3 relevant specialists before responding
- For simple lookups (list competitors, check summary): use Observatory tools directly
- For comprehensive requests ("full analysis", "what should we do about X"): consult 3+ specialists
- Weight specialist selection toward the org's configured lens priorities:
{lens_block}
- Higher-weighted lenses = prioritise those specialists

You also have direct access to all Observatory tools for data retrieval. But for any question requiring interpretation, analysis, or recommendation, delegate to specialists first, then synthesize.

PRODUCT CONTEXT:
- Organisation: {ctx_org['org_name']}
- Product: {ctx_org['product_description']}
- Product Areas: {', '.join(ctx_org['product_areas']) or 'None configured'}
- Competitors: {', '.join(c['name'] for c in ctx_org['competitors']) or 'None configured'}

Respond conversationally using markdown. After consulting specialists, synthesize their findings — highlight agreements, tensions, and your recommended path forward."""

    # Get the user's auth token for internal API calls
    auth_header = request.headers.get("authorization", "")
    token = auth_header.replace("Bearer ", "") if auth_header else ""
    tool_api_v1 = f"http://localhost:8000/api/v1/orgs/{org_id}"
    tool_headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # ── Cost-controlled limits for chat ──
    chat_limits = tracker._get_limits(org_id)

    def run_specialist(specialist_name, question, context_text):
        """Run a nested specialist agent loop with cost controls."""
        spec_prompt = build_specialist_prompt(specialist_name, ctx_org)
        spec_tools = get_specialist_tools(specialist_name, AGENT_TOOLS)
        spec_client = anthropic.Anthropic(api_key=api_key)
        spec_messages = [{"role": "user", "content": f"{question}\n\nContext: {context_text}" if context_text else question}]
        events = []
        spec_text = ""
        max_spec_tokens = min(3000, chat_limits.max_tokens_per_request)

        for _ in range(chat_limits.max_specialist_iterations):
            # Budget check before each specialist Claude call
            ok, reason = guard_anthropic(org_id, CLAUDE_MODEL, max_spec_tokens)
            if not ok:
                spec_text += f"\n[Specialist stopped: {reason}]"
                break
            try:
                spec_response = spec_client.messages.create(
                    model=CLAUDE_MODEL,
                    max_tokens=max_spec_tokens,
                    system=spec_prompt,
                    tools=spec_tools,
                    messages=spec_messages,
                )
                # Log actual usage
                log_anthropic_usage(org_id, CLAUDE_MODEL, f"specialist/{specialist_name}",
                                    spec_response.usage.input_tokens, spec_response.usage.output_tokens)
            except Exception as e:
                return f"Error consulting specialist: {e}", events

            spec_content = spec_response.content
            spec_messages.append({"role": "assistant", "content": spec_content})

            for block in spec_content:
                if block.type == "text":
                    spec_text += block.text

            if spec_response.stop_reason == "end_turn":
                break

            # Execute specialist tool calls
            tool_results = []
            for block in spec_content:
                if block.type == "tool_use":
                    events.append({"type": "specialist_tool", "specialist": specialist_name, "tool": block.name, "status": "running"})
                    try:
                        result = agent_execute_tool(block.name, block.input, tool_api_v1, tool_headers)
                    except Exception as e:
                        result = json.dumps({"error": str(e)})
                    events.append({"type": "specialist_tool", "specialist": specialist_name, "tool": block.name, "status": "done"})
                    tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})

            if tool_results:
                spec_messages.append({"role": "user", "content": tool_results})

        return spec_text, events

    def event_stream():
        client = anthropic.Anthropic(api_key=api_key)
        full_text = ""
        tool_calls_list = []
        specialist_consults_this_turn = 0
        max_cco_tokens = min(4096, chat_limits.max_tokens_per_request)

        for iteration in range(chat_limits.max_chat_iterations):
            # Budget check before each CCO Claude call
            ok, reason = guard_anthropic(org_id, CLAUDE_MODEL, max_cco_tokens)
            if not ok:
                yield f"data: {json.dumps({'type': 'error', 'message': f'Cost limit reached: {reason}'})}\n\n"
                break
            try:
                with client.messages.stream(
                    model=CLAUDE_MODEL,
                    max_tokens=max_cco_tokens,
                    system=system,
                    tools=AGENT_TOOLS,
                    messages=messages,
                ) as stream:
                    for event in stream:
                        if event.type == "content_block_start":
                            if hasattr(event.content_block, "type") and event.content_block.type == "tool_use":
                                yield f"data: {json.dumps({'type': 'tool_start', 'name': event.content_block.name})}\n\n"
                        elif event.type == "content_block_delta":
                            if hasattr(event.delta, "type") and event.delta.type == "text_delta":
                                full_text += event.delta.text
                                yield f"data: {json.dumps({'type': 'text', 'content': event.delta.text})}\n\n"

                    response = stream.get_final_message()
                    # Log actual usage for the CCO call
                    log_anthropic_usage(org_id, CLAUDE_MODEL, "chat/cco",
                                        response.usage.input_tokens, response.usage.output_tokens)
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
                break

            assistant_content = response.content
            messages.append({"role": "assistant", "content": assistant_content})

            if response.stop_reason == "end_turn":
                break

            # Execute tool calls
            tool_results = []
            for block in assistant_content:
                if block.type == "tool_use":
                    tool_calls_list.append({"id": block.id, "name": block.name, "input": block.input})

                    # Special handling for consult_specialist
                    if block.name == "consult_specialist":
                        # Enforce specialist consult cap per turn
                        if specialist_consults_this_turn >= chat_limits.max_specialist_consults_per_turn:
                            tool_results.append({"type": "tool_result", "tool_use_id": block.id,
                                                 "content": f"Specialist consultation limit reached ({chat_limits.max_specialist_consults_per_turn} per turn). Synthesize from the specialists already consulted."})
                            continue

                        specialist_name = block.input.get("specialist", "")
                        spec_question = block.input.get("question", "")
                        spec_context = block.input.get("context", "")
                        display_name = SPECIALISTS.get(specialist_name, {}).get("display_name", specialist_name)

                        yield f"data: {json.dumps({'type': 'specialist_start', 'specialist': specialist_name, 'display_name': display_name, 'question': spec_question})}\n\n"

                        spec_result, spec_events = run_specialist(specialist_name, spec_question, spec_context)
                        specialist_consults_this_turn += 1

                        # Emit specialist's tool activity
                        for se in spec_events:
                            yield f"data: {json.dumps(se)}\n\n"

                        preview = spec_result[:300] + "..." if len(spec_result) > 300 else spec_result
                        yield f"data: {json.dumps({'type': 'specialist_done', 'specialist': specialist_name, 'display_name': display_name, 'preview': preview})}\n\n"

                        tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": spec_result})
                    else:
                        # Regular Observatory tool
                        try:
                            result = agent_execute_tool(block.name, block.input, tool_api_v1, tool_headers)
                        except Exception as e:
                            result = json.dumps({"error": str(e)})
                        preview = result[:200] + "..." if len(result) > 200 else result
                        yield f"data: {json.dumps({'type': 'tool_result', 'name': block.name, 'preview': preview})}\n\n"
                        tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})

            if tool_results:
                messages.append({"role": "user", "content": tool_results})

        # Save assistant message to DB
        save_conn = get_db()
        assistant_msg_id = str(uuid.uuid4())
        save_conn.execute(
            "INSERT INTO chat_messages (id, conversation_id, role, content, tool_calls_json) VALUES (?, ?, 'assistant', ?, ?)",
            (assistant_msg_id, conv_id, full_text, json.dumps(tool_calls_list) if tool_calls_list else None)
        )
        save_conn.commit()
        save_conn.close()

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ─── Cost Control Endpoints ────────────────────────────────────────────────

@app.get("/api/v1/orgs/{org_id}/costs")
def get_costs(org_id: str, ctx: tuple[str, str] = Depends(require_org)):
    """Get real-time spend dashboard: daily/monthly totals, per-service breakdown, limits, recent calls."""
    check_org(org_id, ctx)
    return tracker.get_spend_summary(org_id)


class BudgetUpdateIn(BaseModel):
    daily_anthropic: float | None = None
    daily_perplexity: float | None = None
    daily_firecrawl: float | None = None
    daily_serpapi: float | None = None
    daily_total: float | None = None
    monthly_anthropic: float | None = None
    monthly_perplexity: float | None = None
    monthly_firecrawl: float | None = None
    monthly_serpapi: float | None = None
    monthly_total: float | None = None
    max_tokens_per_request: int | None = None
    max_chat_iterations: int | None = None
    max_specialist_iterations: int | None = None
    max_crawl_pages: int | None = None
    max_specialist_consults_per_turn: int | None = None


@app.patch("/api/v1/orgs/{org_id}/costs/limits")
def update_cost_limits(org_id: str, body: BudgetUpdateIn, ctx: tuple[str, str] = Depends(require_org)):
    """Update spending limits for this org. Only owner/admin should call this."""
    check_org(org_id, ctx)
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No limits provided")
    # Merge with existing
    current = tracker._get_limits(org_id)
    merged = {}
    for field in vars(current):
        if not field.startswith("_"):
            merged[field] = updates.get(field, getattr(current, field))
    tracker.update_limits(org_id, merged)
    return {"ok": True, "limits": merged}


@app.get("/api/v1/orgs/{org_id}/costs/history")
def cost_history(org_id: str, days: int = 7, ctx: tuple[str, str] = Depends(require_org)):
    """Get daily spend totals for the last N days."""
    check_org(org_id, ctx)
    conn = get_db()
    rows = conn.execute(
        """SELECT date(created_at) as day, service,
                  COALESCE(SUM(estimated_cost_gbp), 0) as total,
                  COUNT(*) as calls
           FROM api_cost_log
           WHERE org_id = ? AND created_at >= date('now', ?)
           GROUP BY day, service
           ORDER BY day DESC""",
        (org_id, f"-{days} days")
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/health")
def health():
    return {"status": "healthy", "version": "0.5.0-cost-controls", "mode": "sqlite", "claude": ANTHROPIC_AVAILABLE}


if __name__ == "__main__":
    print("\n  Starting Observatory Dev Server (Claude-powered)...\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)
