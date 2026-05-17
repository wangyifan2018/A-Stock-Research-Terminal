import { getOpenFrApiBaseUrl } from "./api";

export type MarketCandle = {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
};

export type MarketMetric = {
  label: string;
  value: string;
  delta?: string;
  trend?: "up" | "down" | "flat";
  source?: string;
};

export type MarketSnapshot = {
  ticker: string;
  code: string;
  updated_at: string;
  stale: boolean;
  source?: string;
  candles: MarketCandle[];
  metrics: MarketMetric[];
  errors: string[];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function num(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

/** Validates `/api/v1/market/snapshot` JSON so malformed proxies cannot crash the dashboard. */
export function parseMarketSnapshotPayload(raw: unknown): MarketSnapshot {
  if (!isRecord(raw)) {
    throw new Error("Market snapshot: expected JSON object");
  }

  const ticker = raw.ticker;
  const code = raw.code;
  const updated_at = raw.updated_at;
  if (typeof ticker !== "string" || typeof code !== "string" || typeof updated_at !== "string") {
    throw new Error("Market snapshot: missing ticker, code, or updated_at");
  }

  const stale = Boolean(raw.stale);
  const source = typeof raw.source === "string" ? raw.source : undefined;

  const candlesRaw = raw.candles;
  const candles: MarketCandle[] = [];
  if (!Array.isArray(candlesRaw)) {
    throw new Error("Market snapshot: candles must be an array");
  }
  for (const row of candlesRaw) {
    if (!isRecord(row)) continue;
    const time = num(row.time);
    const open = num(row.open);
    const high = num(row.high);
    const low = num(row.low);
    const close = num(row.close);
    if (time === null || open === null || high === null || low === null || close === null) continue;
    candles.push({ time: Math.trunc(time), open, high, low, close });
  }

  const metricsRaw = raw.metrics;
  const metrics: MarketMetric[] = [];
  if (!Array.isArray(metricsRaw)) {
    throw new Error("Market snapshot: metrics must be an array");
  }
  for (const row of metricsRaw) {
    if (!isRecord(row)) continue;
    const label = row.label;
    const value = row.value;
    if (typeof label !== "string" || typeof value !== "string") continue;
    const metric: MarketMetric = { label, value };
    if (typeof row.delta === "string") metric.delta = row.delta;
    if (row.trend === "up" || row.trend === "down" || row.trend === "flat") metric.trend = row.trend;
    if (typeof row.source === "string") metric.source = row.source;
    metrics.push(metric);
  }

  const errorsRaw = raw.errors;
  const errors: string[] = [];
  if (Array.isArray(errorsRaw)) {
    for (const e of errorsRaw) {
      if (typeof e === "string") errors.push(e);
    }
  }

  return { ticker, code, updated_at, stale, source, candles, metrics, errors };
}

export async function fetchMarketSnapshot(ticker: string, signal?: AbortSignal): Promise<MarketSnapshot> {
  const apiBase = getOpenFrApiBaseUrl();
  const url = new URL(`${apiBase}/api/v1/market/snapshot`);
  url.searchParams.set("ticker", ticker);

  const response = await fetch(url.toString(), {
    headers: { Accept: "application/json" },
    signal
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new Error("Market snapshot: invalid JSON body");
  }

  return parseMarketSnapshotPayload(payload);
}
