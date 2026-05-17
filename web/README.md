# A-Stock Research Terminal Web Dashboard

Next.js 14 + Tailwind CSS + Shadcn UI + Radix Collapsible + Lucide React + Lightweight Charts 投研工作台。

This dashboard is the visual cockpit for the FastAPI/LangGraph backend:

- left-side K-line and financial metric panels
- right-side AI Research Terminal
- phase stepper for `Data Intel -> Bull vs Bear -> Risk Control`
- Bull/Bear versus chat bubbles
- collapsible analyst logs
- sticky final verdict
- Copy Markdown and Export PDF after stream completion
- `dashboard_snapshot` sync from the backend SSE stream to the left chart

## Project Structure

```txt
web/
  src/app/
    globals.css
    layout.tsx
    page.tsx
  src/components/
    dashboard/
      market-chart.tsx
      metric-cards.tsx
      research-terminal-events.ts
      research-terminal.tsx
      sparkline.tsx
    ui/
      badge.tsx
      button.tsx
      card.tsx
      collapsible.tsx
      input.tsx
  src/lib/
    api.ts
    market-snapshot.ts
    utils.ts
  components.json
  tailwind.config.ts
  package.json
```

## Install

```bash
cd web
npm install
cp .env.example .env.local
npm run dev
```

The dashboard expects the FastAPI backend at:

```txt
NEXT_PUBLIC_OPENFR_API_BASE_URL=http://localhost:8000
```

## Shadcn UI Commands

If you want to regenerate the UI primitives with the Shadcn CLI:

```bash
cd web
npx shadcn-ui@latest init
npx shadcn-ui@latest add button input card badge collapsible
```

With the newer CLI name, the equivalent commands are:

```bash
npx shadcn@latest init
npx shadcn@latest add button input card badge collapsible
```

## SSE Contract

The terminal sends:

```http
POST /api/v1/research/stream
Content-Type: application/json
Accept: text/event-stream
```

Payload:

```json
{
  "ticker": "sh600519",
  "depth": "deep"
}
```

It renders `start`, `agent_step`, `complete`, and `error` events from the OpenFR FastAPI service.

When an `agent_step` contains `dashboard_snapshot`, `ResearchTerminal` pushes it to page-level state so `MarketChart` and `MetricCards` use the same data collected during the right-side research run.

## Quality Checks

```bash
npm run typecheck
npm run test
npm run build
```
