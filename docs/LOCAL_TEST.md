# Local Testing Checklist

Use this guide to verify **API**, **SSE research stream**, **Agent Snapshot Sync**, and the **web dashboard** before publishing or opening a PR.

## 1. Environment variables

The Python stack loads, in order:

1. Repository root `.env`
2. Repository root `.env.local` (values override `.env` when the same key appears in both)

Minimum for **Zhipu**:

```bash
OPENFR_PROVIDER=zhipu
ZHIPU_API_KEY=your_key
# optional
OPENFR_MODEL=glm-4.7
```

Frontend reads **`web/.env.local`** only (Next.js convention):

```bash
NEXT_PUBLIC_OPENFR_API_BASE_URL=http://localhost:8000
```

A starter `web/.env.local` can be copied from `web/.env.example`.

**Docker Compose** ([docker-compose.yml](docker-compose.yml)) uses `env_file: .env` at the repo root only. Copy your secrets to `.env` before `docker compose up`, or symlink `.env` → `.env.local` if you keep keys only in `.env.local`.

## 2. Bare-metal API

Requires **Python ≥ 3.10** (project default).

```bash
cd /path/to/openfr
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements_api.txt
.venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Smoke tests:

```bash
curl -sS http://127.0.0.1:8000/health
# expect: {"status":"ok","service":"openfr-api"}

curl -sS -N --max-time 60 -X POST http://127.0.0.1:8000/api/v1/research/stream \
  -H 'Content-Type: application/json' \
  -H 'Accept: text/event-stream' \
  -d '{"ticker":"600519","depth":"quick"}'
# expect: event: start ... event: agent_step ... (full run may take minutes)
```

## 3. Bare-metal web

```bash
cd web
npm install
npm run dev
```

Open `http://localhost:3000`, enter a ticker, click **Run Deep Research**. The browser must reach the API URL in `NEXT_PUBLIC_OPENFR_API_BASE_URL`.

## 4. Docker Compose (optional)

Prerequisites: **Docker Desktop** (or Docker Engine + Compose plugin) installed; `docker compose version` works.

```bash
# Ensure repo root has .env with API keys (see section 1)
docker compose up --build
```

Then:

- Dashboard: `http://localhost:3000`
- API health: `http://localhost:8000/health`

The web image is built with `NEXT_PUBLIC_OPENFR_API_BASE_URL=http://localhost:8000`, which is correct when the browser runs on your machine and the API is published on host port `8000`.

If Docker is not installed, install from [Docker documentation](https://docs.docker.com/get-docker/) and retry.

## 5. Automated tests (no live LLM required)

```bash
.venv/bin/python -m pytest \
  tests/test_api_stream.py \
  tests/test_market_snapshot_api.py \
  tests/test_network_resilience.py \
  tests/test_stability_hardening.py \
  tests/test_akshare_compat.py
```

Integration tests that call real LLMs expect repo root `.env`; see [tests/test_integration.py](../tests/test_integration.py).

Frontend checks:

```bash
cd web
npm run typecheck
npm run test
npm run build
```

## 6. Agent Snapshot Sync checklist

During a successful Deep Research run:

1. The right terminal should show `Data Intel -> Bull vs Bear -> Risk Control`.
2. The `Fundamentals Analyst` SSE event may include `dashboard_snapshot`.
3. The left K-line panel should switch from `FALLBACK OHLC` / `AKSHARE OHLC` to `AGENT SNAPSHOT OHLC` when the structured snapshot arrives.
4. `Copy Markdown` and `Export PDF` should only be enabled after `event: complete`.

## 7. Known safety defaults

`py_mini_racer` and 同花顺 fallback data paths are disabled by default because some macOS/Python combinations can crash at the native layer.

Do not enable these unless you are testing in an isolated environment:

```bash
OPENFR_ENABLE_THS_DATA=1
OPENFR_ENABLE_MINI_RACER=1
```
