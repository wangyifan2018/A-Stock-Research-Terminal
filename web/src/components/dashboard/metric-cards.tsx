"use client";

import { useMemo } from "react";
import { Activity, BarChart3, Landmark, Percent, type LucideIcon } from "lucide-react";

import { DataSourceScanRibbon } from "@/components/dashboard/data-source-scan";
import { Sparkline, buildSparkSeries } from "@/components/dashboard/sparkline";
import { Card } from "@/components/ui/card";
import type { MarketMetric } from "@/lib/market-snapshot";

type MetricDef = {
  label: string;
  tone: string;
  icon: LucideIcon;
  format: (value: number) => string;
  range: [number, number];
};

const METRICS: MetricDef[] = [
  {
    label: "PE",
    tone: "text-cyan-200",
    icon: Activity,
    range: [12, 46],
    format: (value) => `${value.toFixed(1)}x`
  },
  {
    label: "PB",
    tone: "text-violet-200",
    icon: BarChart3,
    range: [1.2, 9.5],
    format: (value) => `${value.toFixed(1)}x`
  },
  {
    label: "ROE",
    tone: "text-emerald-200",
    icon: Percent,
    range: [5, 35],
    format: (value) => `${value.toFixed(1)}%`
  },
  {
    label: "市值",
    tone: "text-amber-200",
    icon: Landmark,
    range: [0.08, 2.8],
    format: (value) => `${value.toFixed(2)}T`
  }
];

type MetricCardsProps = {
  ticker: string;
  metrics?: MarketMetric[];
  isLoading?: boolean;
};

export function MetricCards({ ticker, metrics: realMetrics = [], isLoading = false }: MetricCardsProps) {
  const rows = useMemo(
    () =>
      METRICS.map((metric, index) => {
        const spark = buildSparkSeries([ticker.toLowerCase(), metric.label], 36, index !== 1);
        const start = spark[0] ?? 0;
        const end = spark.at(-1) ?? start;
        const min = Math.min(...spark);
        const max = Math.max(...spark);
        const ratio = max === min ? 0.5 : (end - min) / (max - min);
        const value = metric.range[0] + ratio * (metric.range[1] - metric.range[0]);
        const delta = start === 0 ? 0 : ((end - start) / Math.abs(start)) * 100;
        const trendUp = end >= start;
        const realMetric = realMetrics.find((item) => item.label === metric.label);
        return {
          ...metric,
          value: realMetric?.value || metric.format(value),
          delta: realMetric?.delta || `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}%`,
          trendUp: realMetric?.trend ? realMetric.trend !== "down" : trendUp,
          spark
        };
      }),
    [realMetrics, ticker]
  );

  return (
    <div className="relative">
      <DataSourceScanRibbon active={isLoading} />
      <div className="grid grid-cols-2 gap-4">
      {rows.map((metric) => {
        const Icon = metric.icon;

        return (
          <Card
            key={metric.label}
            className="group relative overflow-hidden p-5 transition duration-300 hover:-translate-y-0.5 hover:border-cyan-300/30"
          >
            <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-cyan-300/50 to-transparent" />
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-2">
                  <p className="font-mono text-xs uppercase tracking-[0.3em] text-slate-500">
                    {metric.label}
                  </p>
                  <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-600">
                    36M roll
                  </p>
                </div>

                <div className="relative mt-2 min-h-[3rem]">
                  <Sparkline
                    values={metric.spark}
                    vbHeight={30}
                    trendPositive={metric.trendUp}
                    className="pointer-events-none absolute inset-x-[-6px] bottom-[-4px] top-1 h-[calc(100%+2px)] w-[calc(100%+12px)] opacity-[0.32]"
                  />
                  <p
                    className={`relative z-10 text-3xl font-semibold tabular-nums tracking-tight drop-shadow-[0_1px_12px_rgba(15,23,42,0.85)] ${metric.tone}`}
                  >
                    {metric.value}
                  </p>
                </div>
              </div>
              <div className="shrink-0 rounded-xl border border-cyan-400/15 bg-cyan-400/10 p-2 text-cyan-200">
                <Icon className="h-5 w-5" />
              </div>
            </div>

            <p className="mt-4 font-mono text-xs text-slate-400">
              signal: <span className="text-emerald-300">{metric.delta}</span>
            </p>
          </Card>
        );
      })}
      </div>
    </div>
  );
}
