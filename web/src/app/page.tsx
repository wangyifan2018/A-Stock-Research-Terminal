"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowUpRight,
  Gauge,
  type LucideIcon,
  Loader2,
  Play,
  Radar,
  ShieldCheck,
  Sparkles
} from "lucide-react";

import { MarketChart } from "@/components/dashboard/market-chart";
import { MetricCards } from "@/components/dashboard/metric-cards";
import { ResearchTerminal } from "@/components/dashboard/research-terminal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { fetchMarketSnapshot, type MarketSnapshot } from "@/lib/market-snapshot";
import { cn } from "@/lib/utils";

export default function Home() {
  const [ticker, setTicker] = useState("sh600519");
  const [activeTicker, setActiveTicker] = useState("sh600519");
  const [runId, setRunId] = useState(0);
  const [isRunning, setIsRunning] = useState(false);
  const [marketSnapshot, setMarketSnapshot] = useState<MarketSnapshot | null>(null);
  const [marketLoading, setMarketLoading] = useState(false);
  const abortResearchRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setMarketLoading(true);
    fetchMarketSnapshot(activeTicker, controller.signal)
      .then((snapshot) => {
        setMarketSnapshot((current) =>
          current?.source === "agent_snapshot" && current.code === snapshot.code ? current : snapshot
        );
      })
      .catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }
        setMarketSnapshot((current) => (current?.source === "agent_snapshot" ? current : null));
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setMarketLoading(false);
        }
      });

    return () => controller.abort();
  }, [activeTicker]);

  const handleAbortReady = useCallback((abort: () => void) => {
    abortResearchRef.current = abort;
  }, []);

  const runResearch = useCallback(() => {
    const normalizedTicker = ticker.trim();
    if (!normalizedTicker) {
      return;
    }

    setActiveTicker(normalizedTicker);
    setMarketSnapshot(null);
    setIsRunning(true);
    setRunId((current) => current + 1);
  }, [ticker]);

  const stopResearch = useCallback(() => {
    abortResearchRef.current?.();
  }, []);

  const handleDone = useCallback(() => {
    setIsRunning(false);
    abortResearchRef.current = null;
  }, []);

  const handleDashboardSnapshot = useCallback((snapshot: MarketSnapshot) => {
    setMarketSnapshot((current) => {
      if (!isSnapshotForTicker(snapshot, activeTicker)) {
        return current;
      }
      return snapshot;
    });
  }, [activeTicker]);

  return (
    <main className="relative min-h-screen overflow-hidden">
      <div className="absolute inset-0 cyber-grid opacity-40" />
      <div className="absolute left-1/2 top-0 h-[28rem] w-[28rem] -translate-x-1/2 rounded-full bg-cyan-400/10 blur-3xl" />

      <div className="relative mx-auto flex min-h-screen w-full max-w-[1800px] flex-col px-6 py-6 lg:px-8">
        <header className="mb-6 rounded-3xl border border-cyan-400/15 bg-slate-950/65 p-5 shadow-neon backdrop-blur-xl">
          <div className="flex flex-col gap-5 xl:flex-row xl:items-center xl:justify-between">
            <div>
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <Badge variant="default">
                  <Sparkles className="mr-1 h-3 w-3" />
                  OpenFR Command Deck
                </Badge>
                <Badge variant="muted">LangGraph</Badge>
                <Badge variant="success">SSE Live</Badge>
              </div>
              <h1 className="text-3xl font-semibold tracking-tight text-cyan-50 md:text-5xl">
                Neural Equity Research
              </h1>
              <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-400">
                深色极客风投研工作台：左侧追踪市场结构与估值指标，右侧实时显示多 Agent 的数据抓取、辩论、风险评估与最终报告生成过程。
              </p>
            </div>

            <div className="flex w-full flex-col gap-3 rounded-2xl border border-cyan-400/15 bg-black/30 p-3 sm:flex-row xl:max-w-xl">
              <div className="relative flex-1">
                <Radar className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-cyan-300/60" />
                <Input
                  value={ticker}
                  onChange={(event) => setTicker(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !isRunning) {
                      runResearch();
                    }
                  }}
                  disabled={isRunning}
                  className="pl-10 font-mono text-base"
                  placeholder="sh600519"
                />
              </div>
              <Button
                size="lg"
                type="button"
                onClick={isRunning ? stopResearch : runResearch}
                disabled={!isRunning && !ticker.trim()}
                className={cn(
                  "gap-2 font-semibold",
                  isRunning
                    ? "bg-red-600 text-white shadow-[0_0_28px_rgba(239,68,68,0.35)] hover:bg-red-500 focus-visible:ring-red-400"
                    : "bg-cyan-300 text-slate-950 hover:bg-cyan-200"
                )}
              >
                {isRunning ? (
                  <>
                    <Loader2 className="h-4 w-4 shrink-0 animate-spin" aria-hidden />
                    Stop Research
                  </>
                ) : (
                  <>
                    <Play className="h-4 w-4 shrink-0" aria-hidden />
                    Run Deep Research
                  </>
                )}
              </Button>
            </div>
          </div>
        </header>

        <section className="grid flex-1 grid-cols-1 gap-6 xl:grid-cols-2">
          <div className="space-y-6">
            <MarketChart
              ticker={activeTicker}
              candles={marketSnapshot?.candles}
              stale={marketSnapshot?.stale}
              source={marketSnapshot?.source}
              isLoading={isRunning || marketLoading}
            />
            <MetricCards
              ticker={activeTicker}
              metrics={marketSnapshot?.metrics}
              isLoading={isRunning || marketLoading}
            />

            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
              <SignalPill icon={Activity} label="Momentum" value="Bullish 73%" />
              <SignalPill icon={Gauge} label="Valuation" value="Neutral" />
              <SignalPill icon={ShieldCheck} label="Risk Guard" value="Stable" />
            </div>
          </div>

          <ResearchTerminal
            ticker={activeTicker}
            depth="deep"
            runId={runId}
            onDone={handleDone}
            onDashboardSnapshot={handleDashboardSnapshot}
            onAbortReady={handleAbortReady}
          />
        </section>
      </div>
    </main>
  );
}

function isSnapshotForTicker(snapshot: MarketSnapshot, ticker: string): boolean {
  const raw = ticker.trim().toLowerCase();
  const normalized = raw.replace(/^(sh|sz|bj)/, "").replace(/\D/g, "");
  return snapshot.ticker.toLowerCase() === raw || snapshot.code === normalized;
}

function SignalPill({
  icon: Icon,
  label,
  value
}: {
  icon: LucideIcon;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center justify-between rounded-2xl border border-cyan-400/15 bg-slate-950/60 p-4 shadow-neon backdrop-blur">
      <div className="flex items-center gap-3">
        <div className="rounded-xl bg-cyan-400/10 p-2 text-cyan-200">
          <Icon className="h-4 w-4" />
        </div>
        <div>
          <p className="text-xs uppercase tracking-[0.25em] text-slate-500">{label}</p>
          <p className="mt-1 font-mono text-sm text-slate-200">{value}</p>
        </div>
      </div>
      <ArrowUpRight className="h-4 w-4 text-emerald-300" />
    </div>
  );
}
