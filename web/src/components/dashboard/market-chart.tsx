"use client";

import { useEffect, useMemo, useRef } from "react";
import {
  ColorType,
  createChart,
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp
} from "lightweight-charts";

import { DataSourceScanRibbon } from "@/components/dashboard/data-source-scan";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle
} from "@/components/ui/card";
import type { MarketCandle } from "@/lib/market-snapshot";

function hashTicker(ticker: string): number {
  let h = 2166136261;
  for (let i = 0; i < ticker.length; i++) {
    h ^= ticker.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function nextRand(seed: number) {
  let s = seed;
  return () => {
    s = Math.imul(s ^ (s >>> 15), s | 1);
    s ^= s + Math.imul(s ^ (s >>> 7), s | 61);
    return ((s ^ (s >>> 14)) >>> 0) / 4294967296;
  };
}

function buildTickerCandles(ticker: string): CandlestickData<UTCTimestamp>[] {
  const seed = hashTicker(ticker || "sh600519");
  const rnd = nextRand(seed);
  const baseTime = 1704067200;
  let close = 80 + (seed % 220);
  const drift = (rnd() - 0.44) * 1.4;

  return Array.from({ length: 44 }, (_, i) => {
    const open = close + (rnd() - 0.5) * 6;
    close = Math.max(6, open + drift + (rnd() - 0.5) * 9);
    const high = Math.max(open, close) + rnd() * 5;
    const low = Math.max(1, Math.min(open, close) - rnd() * 5);
    return {
      time: (baseTime + i * 86400) as UTCTimestamp,
      open: Number(open.toFixed(2)),
      high: Number(high.toFixed(2)),
      low: Number(low.toFixed(2)),
      close: Number(close.toFixed(2))
    };
  });
}

type MarketChartProps = {
  ticker: string;
  candles?: MarketCandle[];
  stale?: boolean;
  source?: string;
  /** AI pipeline is streaming — show global “data feed” scan on this surface */
  isLoading?: boolean;
};

export function MarketChart({
  ticker,
  candles: realCandles = [],
  stale = false,
  source,
  isLoading = false
}: MarketChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const candles = useMemo(
    () =>
      realCandles.length > 0
        ? realCandles.map((item) => ({
            time: item.time as UTCTimestamp,
            open: item.open,
            high: item.high,
            low: item.low,
            close: item.close
          }))
        : buildTickerCandles(ticker),
    [realCandles, ticker]
  );

  useEffect(() => {
    if (!containerRef.current) {
      return;
    }

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 360,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "rgba(226, 232, 240, 0.72)"
      },
      grid: {
        vertLines: { color: "rgba(34, 211, 238, 0.08)" },
        horzLines: { color: "rgba(34, 211, 238, 0.08)" }
      },
      crosshair: {
        mode: 1
      },
      rightPriceScale: {
        borderColor: "rgba(34, 211, 238, 0.18)"
      },
      timeScale: {
        borderColor: "rgba(34, 211, 238, 0.18)",
        timeVisible: true
      }
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderUpColor: "#22c55e",
      borderDownColor: "#ef4444",
      wickUpColor: "#67e8f9",
      wickDownColor: "#fb7185"
    });

    candleSeries.setData([]);
    chart.timeScale().fitContent();
    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;

    const observer = new ResizeObserver(([entry]) => {
      chart.applyOptions({ width: entry.contentRect.width });
    });
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!candleSeriesRef.current || !chartRef.current) {
      return;
    }
    candleSeriesRef.current.setData(candles);
    chartRef.current.timeScale().fitContent();
  }, [candles]);

  return (
    <Card className="relative overflow-hidden">
      <DataSourceScanRibbon active={isLoading} />
      <CardHeader className="flex-row items-center justify-between border-b border-cyan-500/10 pb-4">
        <div>
          <CardTitle className="font-mono text-cyan-100">K-Line Matrix</CardTitle>
          <p className="mt-1 text-xs uppercase tracking-[0.35em] text-cyan-300/60">
            {ticker || "sh600519"} / {realCandles.length > 0 ? chartSourceLabel(source, stale) : "FALLBACK OHLC"}
          </p>
        </div>
        <div
          className={`rounded-full border px-3 py-1 font-mono text-xs ${
            isLoading
              ? "border-cyan-400/40 bg-cyan-400/10 text-cyan-100"
              : "border-emerald-400/30 bg-emerald-400/10 text-emerald-200"
          }`}
        >
          {isLoading ? "INGEST…" : "LIVE READY"}
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div className="relative">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_0%,rgba(34,211,238,0.13),transparent_35%)]" />
          <div ref={containerRef} className="relative h-[360px] w-full" />
        </div>
      </CardContent>
    </Card>
  );
}

function chartSourceLabel(source: string | undefined, stale: boolean): string {
  if (source === "agent_snapshot") {
    return stale ? "AGENT CACHED OHLC" : "AGENT SNAPSHOT OHLC";
  }
  return stale ? "CACHED OHLC" : "AKSHARE OHLC";
}
