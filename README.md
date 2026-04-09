# Observatory

**Consumer Intelligence Platform** — a multi-agent system that acts as your Chief Consumer Officer, powered by Claude.

Observatory combines competitive intelligence gathering, behavioural science, and multi-lens analysis to give product teams a single point of contact for consumer research.

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  Frontend (Next.js 16)           │
│  Chat (CCO) │ Dashboard │ Intel Hub │ Settings   │
└──────────────────────┬──────────────────────────┘
                       │ SSE / REST
┌──────────────────────▼──────────────────────────┐
│              Backend (FastAPI + SQLite)           │
│                                                  │
│  ┌─────────────────────────────────────────┐     │
│  │         Chief Consumer Officer (CCO)     │     │
│  │     Delegates to 8 specialist agents     │     │
│  └────┬───┬───┬───┬───┬───┬───┬───┬────────┘     │
│       │   │   │   │   │   │   │   │              │
│  ┌────▼─┐ │ ┌─▼──┐│┌──▼─┐│┌──▼─┐ │ ┌────▼────┐  │
│  │Behav.│ │ │Clin│││Qual.│││Data│ │ │Business │  │
│  │Sci.  │ │ │Psy.│││Spec│││Sci.│ │ │Strat.   │  │
│  └──────┘ │ └────┘│└────┘│└────┘ │ └─────────┘  │
│       ┌───▼──┐  ┌─▼────┐  ┌─────▼──┐            │
│       │Consu.│  │Clin. │  │UX Res. │            │
│       │Res.  │  │Lead  │  │        │            │
│       └──────┘  └──────┘  └────────┘            │
│                                                  │
│  ┌──────────────────────────────────────────┐    │
│  │           Cost Controls Engine            │    │
│  │  Hard daily/monthly budgets per service   │    │
│  │  Rate limiting │ Token tracking │ Logging  │    │
│  └──────────────────────────────────────────┘    │
└──────────────────────────────────────────────────┘
         │          │          │          │
    Anthropic   Perplexity  Firecrawl   Free APIs
    (Claude)    (Sonar)     (Scrape)    (HN, Reddit)
```

## Features

### CCO Multi-Agent Chat
- Conversational interface with a Chief Consumer Officer persona
- Delegates analytical questions to 2-4 specialist agents automatically
- Each specialist has a rich persona, domain frameworks, and filtered tool access
- Real-time streaming with specialist activity cards in the UI

### 8 Specialist Agents

| Specialist | Domain | Key Frameworks |
|---|---|---|
| Behavioural Scientist | Biases, nudges, habit loops | Kahneman, Cialdini, BJ Fogg |
| Consumer Researcher | Mixed methods, segmentation | JTBD, Kano, VoC |
| Clinical Psychologist | Ethical design, wellbeing | CBT, harm-benefit analysis |
| Qualitative Specialist | Thematic analysis, ethnography | Braun & Clarke, IPA, grounded theory |
| Data Scientist | Causal inference, A/B testing | Bayesian methods, DAGs, CUPED |
| Clinical Lead | Research governance, evidence quality | GRADE, PRISMA, CONSORT |
| UX Researcher | Usability, accessibility | Nielsen heuristics, Baymard, WCAG |
| Business Strategist | Competitive strategy, pricing | Porter's 5, LTV/CAC, Blue Ocean |

### Intelligence Gathering
- **Firecrawl** — Scrape and crawl competitor websites
- **Perplexity** — Web search, competitor news, review scanning
- **SerpAPI** — Academic paper search (Google Scholar)
- **HackerNews** — Social listening via Algolia (free)
- **Reddit** — Community monitoring (free)

### Intelligence Generation (Claude-powered)
- 7-lens competitor battlecards
- Friction scenario detection
- Experiment recommendations
- Cross-cutting insight synthesis
- Research gap identification with briefs
- Executive intelligence digests

### Cost Controls
- Hard daily and monthly spending limits per API service
- Budget checks **before** every paid API call fires
- Per-org configurable limits
- Real-time cost dashboard with spend bars and call logs
- Rate limiting per service (requests/minute)
- Agent loop caps to prevent runaway iterations

### Default Budget Limits (GBP)

| Service | Daily | Monthly | Rate Limit |
|---|---|---|---|
| Anthropic | £5.00 | £50.00 | 20 req/min |
| Perplexity | £2.00 | £20.00 | 10 req/min |
| Firecrawl | £2.00 | £20.00 | 5 req/min |
| SerpAPI | £1.00 | £10.00 | — |
| **Total** | **£10.00** | **£80.00** | — |

---

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- An Anthropic API key

### 1. Backend

```bash
cd backend
pip install fastapi uvicorn httpx bcrypt python-jose anthropic pydantic[email]
python dev_server.py
```

The server starts on `http://localhost:8000`.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

The app starts on `http://localhost:3000`.

### 3. Configure

1. Open `http://localhost:3000` and create an account
2. Complete the 6-step onboarding (product description, areas, competitors, data sources, lens weights)
3. Go to **Settings** and add your Anthropic API key
4. Optionally add Firecrawl and Perplexity keys for intelligence gathering
5. Open **Chat** to talk to the CCO

---

## Project Structure

```
backend/
  dev_server.py       # FastAPI server — all endpoints, Claude integration
  agent_runner.py     # Standalone agent with 21 tools
  specialists.py      # 8 specialist agent definitions + personas
  cost_controls.py    # Budget enforcement, tracking, rate limiting
  observatory_dev.db  # SQLite database (auto-created)

frontend/
  src/
    app/(dashboard)/
      chat/           # CCO chat interface
      costs/          # Cost controls dashboard
      overview/       # Intelligence command centre
      competitors/    # Competitor tracking
      intelligence/   # Intelligence hub
      settings/       # API keys, lenses, product config
      ...
    lib/
      api.ts          # Typed API client
      auth-context.tsx # Auth state management
    components/
      dashboard/
        app-sidebar.tsx # Navigation sidebar
```

## API Endpoints

### Auth
- `POST /api/v1/auth/register` — Create account + org
- `POST /api/v1/auth/login` — Login
- `GET /api/v1/auth/me` — Current user

### Intelligence
- `POST /api/v1/orgs/{id}/intel/scrape-competitor` — Firecrawl scrape
- `POST /api/v1/orgs/{id}/intel/crawl-competitor` — Firecrawl crawl
- `POST /api/v1/orgs/{id}/intel/web-search` — Perplexity search
- `POST /api/v1/orgs/{id}/intel/hackernews-scan` — HN scan (free)
- `POST /api/v1/orgs/{id}/intel/reddit-scan` — Reddit scan (free)
- `POST /api/v1/orgs/{id}/intel/academic-search` — Scholar search
- `POST /api/v1/orgs/{id}/intel/deep-analysis` — Full multi-source analysis

### AI Generation
- `POST /api/v1/orgs/{id}/ai/friction-scenarios` — Generate friction signals
- `POST /api/v1/orgs/{id}/ai/experiment-ideas` — Generate experiments
- `POST /api/v1/orgs/{id}/ai/insights` — Synthesise insights
- `POST /api/v1/orgs/{id}/ai/research-gaps` — Detect knowledge gaps
- `POST /api/v1/orgs/{id}/ai/digest` — Executive digest
- `POST /api/v1/orgs/{id}/ai/ask` — Freeform question

### Chat
- `POST /api/v1/orgs/{id}/chat/conversations` — Create conversation
- `POST /api/v1/orgs/{id}/chat/conversations/{cid}/messages` — Send message (SSE stream)

### Cost Controls
- `GET /api/v1/orgs/{id}/costs` — Spend summary
- `PATCH /api/v1/orgs/{id}/costs/limits` — Update limits
- `GET /api/v1/orgs/{id}/costs/history` — Daily history

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Optional | Fallback API key (can also set per-org in UI) |
| `FIRECRAWL_API_KEY` | Optional | Firecrawl for web scraping |
| `PERPLEXITY_API_KEY` | Optional | Perplexity for web search |
| `SERPAPI_KEY` | Optional | Google Scholar search |

## License

Private — all rights reserved.
