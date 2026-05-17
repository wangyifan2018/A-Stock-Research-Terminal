<div align="center">

# A-Stock-Research-Terminal

### Open-source Bloomberg-style AI research terminal for A-share deep research, multi-agent debate, and cyberpunk real-time dashboards.

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Next.js](https://img.shields.io/badge/Next.js-14-000000?style=for-the-badge&logo=nextdotjs&logoColor=white)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-SSE-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Multi--Agent-6A5ACD?style=for-the-badge)](https://github.com/langchain-ai/langgraph)
[![AKShare](https://img.shields.io/badge/Data-AKShare-FF6B00?style=for-the-badge)](https://github.com/akfamily/akshare)
[![Docker](https://img.shields.io/badge/Run-docker--compose%20up-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://docs.docker.com/compose/)

[Quick Start](#quick-start) • [Features](#features) • [Architecture](#architecture) • [API](#streaming-api) • [Testing](#testing) • [Safety](#safety-notes)

</div>

---

## What Is This?

**A-Stock-Research-Terminal** turns a CLI financial research agent into a full-stack, streaming, multi-agent research cockpit for A-share analysis.

It combines:

- **FastAPI** for the backend API service
- **LangGraph** for multi-agent orchestration
- **AKShare** for free market and financial data
- **Asyncio + thread pools** for non-blocking data collection
- **SQLite cache** for low-frequency financial statements
- **Server-Sent Events** for real-time research streaming
- **Next.js 14 + Tailwind + Shadcn UI** for a cyberpunk research dashboard
- **OpenAI-compatible base URLs** for local vLLM, DeepSeek R1, Ollama-compatible gateways, and hosted providers

This is not another toy chatbot. It is a local-first research engine that lets AI analysts fetch data, debate bull and bear cases, evaluate risk, and stream the final report into a terminal-style dashboard.

---

## Features

- **DeepResearch Terminal**: FastAPI SSE streams LangGraph nodes into a Next.js terminal UI.
- **Three-phase agent workflow**: Data Intel -> Bull vs Bear -> Risk Control.
- **War-room debate view**: Bull and Bear researchers render as left/right versus chat bubbles.
- **Live chart sync**: the left K-line and metric cards can consume the same structured `dashboard_snapshot` collected during the right-side research run.
- **Real data with fallback**: AKShare data, stale cache rescue, and graceful UI fallback when upstream sources are slow or unavailable.
- **Export workflow**: Copy Markdown and Export PDF after the stream completes.
- **Local-first LLMs**: supports OpenAI-compatible `base_url` for local gateways, vLLM, Ollama-compatible proxies, DeepSeek-compatible services, and hosted providers.
- **Hardening for unstable data sources**: bounded worker pools, retry/backoff, SQLite cache, SSE heartbeat, disconnect cleanup, and default mini_racer isolation.

---

## Why It Exists

### Local-First Multi-Agent Research

Your positions, watchlists, factor ideas, prompts, and research flow should not be sprayed across random SaaS dashboards.

A-Stock-Research-Terminal can run against local or self-hosted OpenAI-compatible models, which means your research process stays close to your machine and your strategy stays private.

### Real-Time Streaming Architecture

No more blank loading screens.

The backend streams every LangGraph stage as it happens:

```txt
[Data Fetcher] Fetching live quote, K-line, financial summary, fund flow...
[Fundamental Analyst] ROE is strong but valuation pressure is rising...
[Bull Researcher] Growth premium is still defensible...
[Bear Researcher] Margin compression risk is underpriced...
[Risk Council] Position sizing should be conservative...
[Report Generator] Final report is ready.
```

The frontend renders the process like a live AI war room, with Markdown support and typewriter-style output.

### Zero Bloomberg Subscription

Bloomberg is amazing. Bloomberg is also not priced for most retail investors, independent researchers, students, or quant hobbyists.

DeepResearch-Terminal is the open-source alternative for people who want:

- A-share and HK stock research
- Financial statement summaries
- Historical K-line context
- Fund flow analysis
- Multi-agent investment debate
- Local model support
- A visual dashboard
- No five-figure subscription

---

## Screenshot

The dashboard contains a left-side K-line/financial metric area and a right-side AI Research Terminal with phase tracking, collapsible analyst logs, Bull/Bear debate bubbles, and a sticky final verdict.

> Add public screenshots under `docs/assets/` before publishing a release.

---

## Quick Start

### 1. Clone

```bash
git clone https://github.com/wangyifan2018/A-Stock-Research-Terminal.git
cd A-Stock-Research-Terminal
```

### 2. Configure Environment

Create `.env` in the project root. Optional: add `.env.local` for machine-specific overrides—Python loads `.env` then `.env.local` (later wins). Full checklist: [docs/LOCAL_TEST.md](docs/LOCAL_TEST.md).

For a hosted provider:

```bash
OPENFR_PROVIDER=deepseek
DEEPSEEK_API_KEY=your_api_key
OPENFR_MODEL=deepseek-chat
```

For a local OpenAI-compatible endpoint such as vLLM or a local DeepSeek R1 gateway:

```bash
OPENFR_PROVIDER=custom
OPENFR_BASE_URL=http://host.docker.internal:8001/v1
OPENFR_API_KEY=EMPTY
OPENFR_MODEL=deepseek-r1
CUSTOM_API_STYLE=openai
```

### 3. One Command Launch

```bash
docker-compose up --build
```

Then open:

```txt
http://localhost:3000
```

Backend health check:

```txt
http://localhost:8000/health
```

---

## Manual Development

### Backend

```bash
pip install -r requirements_api.txt
.venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

### Frontend

```bash
cd web
npm install
cp .env.example .env.local
npm run dev
```

Open:

```txt
http://localhost:3000
```

---

## Architecture

```txt
Browser Dashboard
  |
  | POST /api/v1/research/stream
  | text/event-stream
  v
FastAPI SSE Service
  |
  v
LangGraph Research State Machine
  |
  +--> Market Analyst
  +--> Fundamentals Analyst
  |       +--> concurrent quote / K-line / financials / fund flow snapshot
  +--> News Analyst
  +--> Macro Analyst
  |
  +--> Bull Researcher
  +--> Bear Researcher
  +--> Research Manager
  |
  +--> Aggressive Risk Analyst
  +--> Conservative Risk Analyst
  +--> Neutral Risk Analyst
  +--> Portfolio Manager
  |
  v
Streaming Final Report
```

### Backend Highlights

- FastAPI service in `api/main.py`
- SSE endpoint: `POST /api/v1/research/stream`
- Market snapshot endpoint: `GET /api/v1/market/snapshot`
- LangGraph orchestration through `ResearchGraph`
- OpenAI-compatible LLM configuration with custom `base_url`
- Async-safe blocking AKShare calls via thread pool wrappers
- Concurrent tool execution for independent read-only tools
- SQLite cache for financial statements and low-frequency data
- Structured `dashboard_snapshot` propagation from agent prefetch into SSE

### Frontend Highlights

- Next.js 14 App Router in `web/`
- Dark cyberpunk research cockpit
- Lightweight Charts K-line panel
- Financial metric cards
- Markdown AI terminal
- POST-based SSE stream parser
- Typewriter-style multi-agent rendering
- Phase Stepper and Bull/Bear War Room view
- Markdown/PDF export tools

---

## Streaming API

Endpoint:

```http
POST /api/v1/research/stream
Content-Type: application/json
Accept: text/event-stream
```

Request:

```json
{
  "ticker": "sh600519",
  "depth": "deep",
  "base_url": "http://localhost:8001/v1",
  "model": "deepseek-r1",
  "api_key": "EMPTY"
}
```

Events:

```txt
event: start
event: agent_step
event: complete
event: error
```

Example stream payload:

```json
{
  "stage": "risk_analysis",
  "node": "Conservative Analyst",
  "message": "Running conservative risk assessment",
  "content": "The downside risk is mainly valuation compression..."
}
```

When the fundamentals prefetch succeeds, `agent_step` may also include:

```json
{
  "dashboard_snapshot": {
    "ticker": "sh600519",
    "code": "600519",
    "updated_at": "2026-05-18T00:00:00",
    "source": "agent_snapshot",
    "stale": false,
    "candles": [
      { "time": 1704067200, "open": 1, "high": 2, "low": 0.5, "close": 1.5 }
    ],
    "metrics": [
      { "label": "PE", "value": "10.0x", "trend": "flat" }
    ],
    "errors": []
  }
}
```

---

## Local LLMs

DeepResearch-Terminal supports OpenAI-compatible endpoints through `base_url`.

That means you can plug in:

- vLLM
- DeepSeek R1 compatible gateways
- Local model proxies
- OpenRouter-compatible services
- Any `/v1/chat/completions` compatible service supported by LangChain OpenAI bindings

Example:

```bash
OPENFR_PROVIDER=custom
OPENFR_BASE_URL=http://localhost:8001/v1
OPENFR_API_KEY=EMPTY
OPENFR_MODEL=deepseek-r1
```

The same fields can also be passed per request to the streaming API.

---

## Safety Notes

AKShare is synchronous. Running it directly inside FastAPI would block the event loop.

This project wraps blocking data access with worker threads and uses concurrent collection for the fundamentals stage:

- Live quote
- Historical K-line
- Financial summary
- Fund flow

Low-frequency data is cached locally with SQLite to reduce remote calls and lower the risk of rate limiting or IP blocking.

### mini_racer / 同花顺 Safety

Some AKShare/同花顺 paths may load `py_mini_racer` and crash at the native layer on certain macOS/Python combinations. OpenFR disables these paths by default.

Only enable them in an isolated environment known to be stable:

```bash
OPENFR_ENABLE_THS_DATA=1
OPENFR_ENABLE_MINI_RACER=1
```

Useful knobs:

```bash
OPENFR_AKSHARE_MAX_WORKERS=4
OPENFR_TOOL_MAX_WORKERS=3
OPENFR_ENABLE_PARALLEL_SOURCES=false
OPENFR_SNAPSHOT_HISTORY_DAYS=60
OPENFR_TOOL_PARALLEL_TIMEOUT=30
OPENFR_CACHE_BACKEND=sqlite
OPENFR_SQLITE_CACHE_PATH=.openfr_cache/cache.sqlite3
```

---

## Testing

Backend focused regression:

```bash
.venv/bin/python -m pytest tests/test_api_stream.py tests/test_market_snapshot_api.py tests/test_network_resilience.py tests/test_stability_hardening.py -q
```

Frontend:

```bash
cd web
npm run typecheck
npm run test
npm run build
```

Manual checklist: [docs/LOCAL_TEST.md](docs/LOCAL_TEST.md).

---

## Project Structure

```txt
.
├── api/                     # FastAPI SSE service
├── src/openfr/              # Core research graph, agents, tools
├── web/                     # Next.js dashboard
├── docs/                    # Documentation and blog material
├── docker-compose.yml       # One-command full-stack launch
├── Dockerfile.api           # Backend container
└── requirements_api.txt     # API service dependencies
```

---

## Roadmap

- Watchlist and multi-symbol batch research
- Redis cache backend
- User-defined agent roles
- Backtesting-aware research prompts
- Portfolio-level risk dashboard
- Auth and team deployment mode
- Hosted SaaS workspace with private team deployments

---

## Disclaimer

This project is for research, education, and engineering experimentation only.

It is not investment advice, not a broker, not a registered advisor, and not a substitute for independent due diligence. Market data may be delayed, incomplete, or inaccurate. You are responsible for your own decisions.

---

## Star History

If this project saves you one Bloomberg tab, one manual spreadsheet, or one wasted weekend, give it a star and build the future of open financial intelligence with us.
