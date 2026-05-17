# OpenFR Web Dashboard

Next.js 14 + Tailwind CSS + Shadcn UI + Lucide React + Lightweight Charts 投研工作台。

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
      research-terminal.tsx
    ui/
      badge.tsx
      button.tsx
      card.tsx
      input.tsx
  src/lib/
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
npx shadcn-ui@latest add button input card badge
```

With the newer CLI name, the equivalent commands are:

```bash
npx shadcn@latest init
npx shadcn@latest add button input card badge
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
