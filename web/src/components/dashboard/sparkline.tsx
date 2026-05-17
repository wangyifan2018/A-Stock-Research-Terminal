"use client";

import { useId, useMemo } from "react";

import { cn } from "@/lib/utils";

function hashSeed(parts: string[]): number {
  let h = 2166136261;
  for (const part of parts) {
    for (let i = 0; i < part.length; i++) {
      h ^= part.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
  }
  return h >>> 0;
}

function mulberry32(seed: number) {
  return function next() {
    let t = (seed += 0x6d2b79f5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** ~36 monthly samples ≈ 3Y terminal-style micro-series (deterministic per seed). */
export function buildSparkSeries(
  seedParts: string[],
  points: number,
  upward: boolean
): number[] {
  const rnd = mulberry32(hashSeed(seedParts));
  let v = 42 + rnd() * 16;
  const drift = upward ? 0.22 : -0.22;
  const series: number[] = [];
  for (let i = 0; i < points; i++) {
    v += drift + (rnd() - 0.5) * 3.2;
    series.push(v);
  }
  return series;
}

type SparklineProps = {
  values: number[];
  className?: string;
  /** SVG viewBox height units (width fixed at 100). */
  vbHeight?: number;
  /** When set, stroke/fill follow this trend instead of inferring from endpoints. */
  trendPositive?: boolean;
};

export function Sparkline({ values, className, vbHeight = 28, trendPositive }: SparklineProps) {
  const gradId = useId().replace(/:/g, "");

  const { areaD, lineD, up } = useMemo(() => {
    if (values.length < 2) {
      return { areaD: "", lineD: "", up: true };
    }
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || 1;
    const pad = span * 0.12;
    const lo = min - pad;
    const hi = max + pad;
    const w = 100;
    const h = vbHeight;

    const coords = values.map((val, i) => {
      const x = (i / (values.length - 1)) * w;
      const y = h - ((val - lo) / (hi - lo)) * h * 0.82 - h * 0.09;
      return [x, y] as const;
    });

    const lineD = coords.map(([x, y], i) => `${i === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`).join(" ");
    const last = coords[coords.length - 1];
    const first = coords[0];
    const areaD = `${lineD} L ${last[0].toFixed(2)} ${h} L ${first[0].toFixed(2)} ${h} Z`;

    const trendUp = values[values.length - 1] >= values[0];
    return { areaD, lineD, up: trendUp };
  }, [values, vbHeight]);

  const displayUp = trendPositive ?? up;

  if (values.length < 2 || !lineD) {
    return null;
  }

  const stroke = displayUp ? "rgba(52, 211, 153, 0.72)" : "rgba(248, 113, 113, 0.72)";
  const fillStop = displayUp ? "rgb(52, 211, 153)" : "rgb(248, 113, 113)";

  return (
    <svg
      className={cn("block select-none", className)}
      viewBox={`0 0 100 ${vbHeight}`}
      preserveAspectRatio="none"
      aria-hidden
    >
      <defs>
        <linearGradient id={gradId} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor={fillStop} stopOpacity="0.55" />
          <stop offset="100%" stopColor={fillStop} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={areaD} fill={`url(#${gradId})`} />
      <path
        d={lineD}
        fill="none"
        stroke={stroke}
        strokeWidth={1.15}
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
