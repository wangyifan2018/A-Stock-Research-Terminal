"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Bot,
  BrainCircuit,
  Check,
  CheckCircle2,
  ChevronDown,
  Copy,
  FileDown,
  Loader2,
  Plus,
  RadioTower,
  SquareTerminal,
  TrendingDown,
  TrendingUp,
  XCircle
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import {
  buildTerminalMarkdown,
  formatFineTimestamp,
  parseSseBlock,
  stageLabels,
  toTerminalEvent,
  type TerminalEvent
} from "@/components/dashboard/research-terminal-events";
import { getOpenFrApiBaseUrl } from "@/lib/api";
import type { MarketSnapshot } from "@/lib/market-snapshot";
import { cn } from "@/lib/utils";

type ResearchTerminalProps = {
  ticker: string;
  depth: "quick" | "deep";
  runId: number;
  onDone?: () => void;
  onDashboardSnapshot?: (snapshot: MarketSnapshot) => void;
  /** Called when a new stream starts so the parent can wire Stop → AbortController.abort */
  onAbortReady?: (abort: () => void) => void;
};

/** Geek-style role badges: bilingual label + cold neon borders */
const ROLE_BADGE_SKIN = {
  dataFetcher:
    "rounded-md border px-2 py-0.5 text-[11px] font-semibold tracking-wide shadow-[0_0_14px_rgba(56,189,248,0.12)] border-sky-400/45 bg-sky-950/55 text-sky-100",
  fundamental:
    "rounded-md border px-2 py-0.5 text-[11px] font-semibold tracking-wide shadow-[0_0_14px_rgba(52,211,153,0.12)] border-emerald-400/50 bg-emerald-950/45 text-emerald-100",
  risk:
    "rounded-md border px-2 py-0.5 text-[11px] font-semibold tracking-wide shadow-[0_0_16px_rgba(248,113,113,0.18)] border-red-500/55 bg-red-950/50 text-red-100",
  report:
    "rounded-md border px-2 py-0.5 text-[11px] font-semibold tracking-wide shadow-[0_0_18px_rgba(34,211,238,0.22)] border-cyan-400/65 bg-cyan-950/50 text-cyan-50",
  debate:
    "rounded-md border px-2 py-0.5 text-[11px] font-semibold tracking-wide shadow-[0_0_12px_rgba(251,191,36,0.14)] border-amber-400/45 bg-amber-950/35 text-amber-100",
  orchestrator:
    "rounded-md border px-2 py-0.5 text-[11px] font-semibold tracking-wide border-violet-400/40 bg-violet-950/45 text-violet-100",
  synthesis:
    "rounded-md border px-2 py-0.5 text-[11px] font-semibold tracking-wide border-indigo-400/45 bg-indigo-950/45 text-indigo-100",
  system:
    "rounded-md border px-2 py-0.5 text-[11px] font-semibold tracking-wide border-slate-600/45 bg-slate-950/70 text-slate-300",
  error:
    "rounded-md border px-2 py-0.5 text-[11px] font-semibold tracking-wide border-rose-500/55 bg-rose-950/50 text-rose-100"
} as const;

function scrollTerminalBottom(el: HTMLElement | null, behavior: ScrollBehavior = "auto") {
  if (!el) return;
  el.scrollTo({ top: el.scrollHeight, behavior });
}

function isNearBottom(el: HTMLElement, threshold = 96) {
  return el.scrollHeight - el.scrollTop - el.clientHeight < threshold;
}

async function renderMarkdownToPdf(el: HTMLElement, filename: string) {
  const html2canvas = (await import("html2canvas")).default;
  const { jsPDF } = await import("jspdf");

  const canvas = await html2canvas(el, {
    scale: 2,
    useCORS: true,
    logging: false,
    backgroundColor: "#ffffff",
    windowWidth: el.scrollWidth
  });

  const imgData = canvas.toDataURL("image/jpeg", 0.9);
  const pdf = new jsPDF({ orientation: "p", unit: "mm", format: "a4" });
  const pageWidth = pdf.internal.pageSize.getWidth();
  const pageHeight = pdf.internal.pageSize.getHeight();
  const margin = 12;
  const usableH = pageHeight - margin * 2;

  const imgW = pageWidth - margin * 2;
  const imgH = (canvas.height * imgW) / canvas.width;

  let heightLeft = imgH;
  let y = margin;

  pdf.addImage(imgData, "JPEG", margin, y, imgW, imgH);
  heightLeft -= usableH;

  while (heightLeft > 0) {
    y = margin - (imgH - heightLeft);
    pdf.addPage();
    pdf.addImage(imgData, "JPEG", margin, y, imgW, imgH);
    heightLeft -= usableH;
  }

  pdf.save(filename);
}

function resolveRolePresentation(event: TerminalEvent): {
  skin: string;
  badgeText: string;
} {
  const node = event.node ?? "";
  const stage = event.stage ?? "graph";

  if (event.event === "error") {
    return { skin: ROLE_BADGE_SKIN.error, badgeText: "[异常 Error]" };
  }
  if (event.event === "complete") {
    return { skin: ROLE_BADGE_SKIN.report, badgeText: "[最终报告 Final Report]" };
  }
  if (event.event === "start") {
    return { skin: ROLE_BADGE_SKIN.orchestrator, badgeText: "[编排 Orchestrator]" };
  }

  if (node === "Portfolio Manager" || stage === "final") {
    return { skin: ROLE_BADGE_SKIN.report, badgeText: "[最终报告 Final Report]" };
  }

  if (
    stage === "risk_analysis" ||
    node === "Aggressive Analyst" ||
    node === "Conservative Analyst" ||
    node === "Neutral Analyst"
  ) {
    return { skin: ROLE_BADGE_SKIN.risk, badgeText: "[风控官 Risk Guard]" };
  }

  if (node === "Fundamentals Analyst" || node === "tools_fundamentals") {
    return { skin: ROLE_BADGE_SKIN.fundamental, badgeText: "[基本面分析师 Fundamental Analyst]" };
  }

  if (node === "Research Manager" || stage === "synthesis") {
    return { skin: ROLE_BADGE_SKIN.synthesis, badgeText: "[研究经理 Research Manager]" };
  }

  if (
    node === "Bull Researcher" ||
    node === "Bear Researcher" ||
    stage === "debate"
  ) {
    return {
      skin: ROLE_BADGE_SKIN.debate,
      badgeText: `[多空辩论 ${stageLabels.debate}]`
    };
  }

  if (
    stage === "tool_call" ||
    node === "Market Analyst" ||
    node === "News Analyst" ||
    node === "Macro Analyst" ||
    node === "tools_market" ||
    node === "tools_news" ||
    node === "tools_macro" ||
    node.startsWith("Msg Clear")
  ) {
    return { skin: ROLE_BADGE_SKIN.dataFetcher, badgeText: "[数据抓取 Data Fetcher]" };
  }

  if (stage === "data_collection") {
    return {
      skin: ROLE_BADGE_SKIN.dataFetcher,
      badgeText: `[数据抓取 ${event.label}]`
    };
  }

  return {
    skin: ROLE_BADGE_SKIN.system,
    badgeText: `[Agent ${event.label}]`
  };
}

const bootLines: TerminalEvent[] = [
  {
    id: "boot-1",
    event: "start",
    label: "System",
    message: "OpenFR neural research console is standing by.",
    content: "等待输入股票代码并启动 Deep Research。",
    stage: "graph"
  }
];

type VerdictTone = "bullish" | "bearish" | "neutral" | "waiting";
type ResearchPhase = "data" | "debate" | "risk";

const PHASES: Array<{
  id: ResearchPhase;
  step: string;
  title: string;
  caption: string;
}> = [
  { id: "data", step: "01", title: "Data Intel", caption: "Analyst mesh" },
  { id: "debate", step: "02", title: "Bull vs Bear", caption: "War room" },
  { id: "risk", step: "03", title: "Risk Control", caption: "Guard rails" }
];

function eventPhase(event: TerminalEvent): ResearchPhase | null {
  const node = event.node ?? "";
  const stage = event.stage ?? "";

  if (event.event === "complete" || stage === "final" || node === "Portfolio Manager") {
    return "risk";
  }
  if (
    stage === "risk_analysis" ||
    node === "Aggressive Analyst" ||
    node === "Conservative Analyst" ||
    node === "Neutral Analyst"
  ) {
    return "risk";
  }
  if (stage === "debate" || node === "Bull Researcher" || node === "Bear Researcher" || node === "Research Manager") {
    return "debate";
  }
  if (
    stage === "data_collection" ||
    stage === "tool_call" ||
    node === "Market Analyst" ||
    node === "Fundamentals Analyst" ||
    node === "News Analyst" ||
    node === "Macro Analyst" ||
    node.startsWith("tools_")
  ) {
    return "data";
  }
  return null;
}

function activePhaseFromEvents(events: TerminalEvent[], status: string): ResearchPhase | null {
  if (status === "COMPLETE") {
    return "risk";
  }
  for (const event of [...events].reverse()) {
    const phase = eventPhase(event);
    if (phase) {
      return phase;
    }
  }
  return null;
}

function phaseIndex(phase: ResearchPhase | null): number {
  return phase ? PHASES.findIndex((item) => item.id === phase) : -1;
}

function isDebateEvent(event: TerminalEvent): boolean {
  return event.node === "Bull Researcher" || event.node === "Bear Researcher";
}

function debateSide(event: TerminalEvent): "bull" | "bear" {
  return event.node === "Bear Researcher" ? "bear" : "bull";
}

function extractFinalVerdict(events: TerminalEvent[]): string {
  const finalEvent =
    [...events].reverse().find((event) => event.event === "complete" && event.content.trim()) ??
    [...events].reverse().find((event) => event.stage === "final" && event.content.trim());

  if (!finalEvent) {
    return "";
  }

  const cleanedLines = finalEvent.content
    .replace(/[#*_`>-]/g, "")
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean);
  const verdictLine =
    cleanedLines.find((line) => /(最终|结论|建议|评级|短线|中线|长期|decision|recommendation)/i.test(line)) ??
    cleanedLines[0] ??
    finalEvent.message;

  return verdictLine.length > 72 ? `${verdictLine.slice(0, 72)}...` : verdictLine;
}

function getVerdictTone(verdict: string): VerdictTone {
  if (!verdict) {
    return "waiting";
  }
  if (/(卖出|减仓|看空|回避|规避|bear|sell|reduce|underperform)/i.test(verdict)) {
    return "bearish";
  }
  if (/(买入|增持|看多|加仓|bull|buy|overweight|outperform)/i.test(verdict)) {
    return "bullish";
  }
  return "neutral";
}

function summarizeEvent(event: TerminalEvent): string {
  const text = (event.message || event.content || "Agent step completed.").replace(/\s+/g, " ").trim();
  return text.length > 56 ? `${text.slice(0, 56)}...` : text;
}

export function ResearchTerminal({
  ticker,
  depth,
  runId,
  onDone,
  onDashboardSnapshot,
  onAbortReady
}: ResearchTerminalProps) {
  const [events, setEvents] = useState<TerminalEvent[]>(bootLines);
  const [isStreaming, setIsStreaming] = useState(false);
  const [copiedMd, setCopiedMd] = useState(false);
  const [pdfBusy, setPdfBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const shouldAutoScrollRef = useRef(true);
  const autoScrollFrameRef = useRef<number | null>(null);
  const pdfExportRef = useRef<HTMLDivElement | null>(null);
  const copyMdResetRef = useRef<number | null>(null);
  const onDashboardSnapshotRef = useRef(onDashboardSnapshot);
  const onAbortReadyRef = useRef(onAbortReady);
  onDashboardSnapshotRef.current = onDashboardSnapshot;
  onAbortReadyRef.current = onAbortReady;

  useEffect(
    () => () => {
      if (copyMdResetRef.current !== null) {
        window.clearTimeout(copyMdResetRef.current);
      }
    },
    []
  );

  const scheduleAutoScroll = useCallback((behavior: ScrollBehavior = "smooth") => {
    if (!shouldAutoScrollRef.current) {
      return;
    }
    if (autoScrollFrameRef.current !== null) {
      window.cancelAnimationFrame(autoScrollFrameRef.current);
    }
    autoScrollFrameRef.current = window.requestAnimationFrame(() => {
      scrollTerminalBottom(scrollRef.current, behavior);
      autoScrollFrameRef.current = null;
    });
  }, []);

  useEffect(() => {
    scheduleAutoScroll("smooth");
  }, [events, scheduleAutoScroll]);

  useEffect(
    () => () => {
      if (autoScrollFrameRef.current !== null) {
        window.cancelAnimationFrame(autoScrollFrameRef.current);
      }
    },
    []
  );

  useEffect(() => {
    if (runId === 0) {
      return;
    }

    let suppressAbortUi = false;
    const controller = new AbortController();
    shouldAutoScrollRef.current = true;
    setEvents([]);
    setIsStreaming(true);
    onAbortReadyRef.current?.(() => controller.abort());

    void streamResearch({
      ticker,
      depth,
      signal: controller.signal,
      onEvent: (event) => {
        if (event.dashboardSnapshot) {
          onDashboardSnapshotRef.current?.(event.dashboardSnapshot);
        }
        setEvents((current) => [...current, event]);
      },
      onAborted: () => {
        if (suppressAbortUi) {
          return;
        }
        setEvents((current) => [
          ...current,
          {
            id: crypto.randomUUID(),
            event: "agent_step",
            label: "System",
            message: "Research stream aborted.",
            content: "用户已中止 SSE 流式研究任务。",
            stage: "graph",
            node: "Orchestrator",
            ts: Date.now()
          }
        ]);
      },
      onError: (message) =>
        setEvents((current) => [
          ...current,
          {
            id: crypto.randomUUID(),
            event: "error",
            label: "Error",
            message,
            content: "后端流式接口返回异常，请检查 API 服务和 CORS 配置。",
            stage: "graph",
            ts: Date.now()
          }
        ])
    }).finally(() => {
      setIsStreaming(false);
      onDone?.();
    });

    return () => {
      suppressAbortUi = true;
      controller.abort();
    };
  }, [depth, onDone, runId, ticker]);

  const status = useMemo(() => {
    if (isStreaming) {
      return "STREAMING";
    }

    const last = events.at(-1);
    if (last?.event === "complete") {
      return "COMPLETE";
    }
    if (last?.event === "error") {
      return "ERROR";
    }
    return "IDLE";
  }, [events, isStreaming]);

  /** SSE terminal closed after `event: complete` — matches backend [DONE] / complete payload. */
  const exportReady = status === "COMPLETE" && !isStreaming;

  const finalVerdict = useMemo(() => extractFinalVerdict(events), [events]);
  const verdictTone = useMemo(() => getVerdictTone(finalVerdict), [finalVerdict]);
  const activeEventId = isStreaming ? events.at(-1)?.id : undefined;
  const activePhase = useMemo(() => activePhaseFromEvents(events, status), [events, status]);

  const exportMarkdown = useMemo(
    () => buildTerminalMarkdown(events, ticker, depth, (event) => resolveRolePresentation(event).badgeText),
    [events, ticker, depth]
  );

  const copyMarkdown = async () => {
    if (!exportReady) {
      return;
    }
    try {
      await navigator.clipboard.writeText(exportMarkdown);
      setCopiedMd(true);
      if (copyMdResetRef.current !== null) {
        window.clearTimeout(copyMdResetRef.current);
      }
      copyMdResetRef.current = window.setTimeout(() => {
        setCopiedMd(false);
        copyMdResetRef.current = null;
      }, 1600);
    } catch {
      // clipboard may be denied — fail quietly in prod UI
    setCopiedMd(false);
    }
  };

  const downloadPdf = async () => {
    if (!exportReady || pdfBusy) {
      return;
    }
    const el = pdfExportRef.current;
    if (!el) {
      return;
    }
    setPdfBusy(true);
    try {
      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      });
      const safe = ticker.replace(/[^\w.-]+/g, "_") || "export";
      await renderMarkdownToPdf(el, `openfr-${safe}-${Date.now()}.pdf`);
    } finally {
      setPdfBusy(false);
    }
  };

  return (
    <Card className="relative flex h-[calc(100vh-120px)] min-h-0 flex-col overflow-hidden border-emerald-400/20 bg-black/80 shadow-terminal">
      <div className="pointer-events-none absolute inset-0 cyber-grid opacity-30" />
      <div className="pointer-events-none absolute inset-x-0 top-0 h-24 animate-scan bg-gradient-to-b from-emerald-300/10 to-transparent" />

      <div className="relative flex items-center justify-between border-b border-emerald-400/15 bg-slate-950/80 px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="rounded-xl border border-emerald-400/30 bg-emerald-400/10 p-2 text-emerald-200">
            <SquareTerminal className="h-5 w-5" />
          </div>
          <div>
            <h2 className="font-mono text-lg font-semibold text-emerald-100">
              AI Research Terminal
            </h2>
            <p className="font-mono text-xs uppercase tracking-[0.3em] text-emerald-300/60">
              POST SSE /api/v1/research/stream
            </p>
          </div>
        </div>
        <div className="flex flex-shrink-0 items-center gap-2">
          <div
            className={cn(
              "flex items-center gap-0.5 rounded-lg border px-0.5 py-0.5 shadow-none transition-all duration-300",
              exportReady
                ? "border-emerald-400/40 bg-emerald-400/[0.07] shadow-[0_0_22px_rgba(16,185,129,0.14)]"
                : "border-slate-700/35 bg-slate-950/50 opacity-[0.38]"
            )}
            title={exportReady ? "Export deck" : "Available after stream completes (complete / DONE)"}
          >
            <button
              type="button"
              onClick={() => void copyMarkdown()}
              disabled={!exportReady}
              aria-label="Copy Markdown"
              title="Copy Markdown"
              className={cn(
                "rounded-md p-1.5 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-emerald-400/60",
                exportReady
                  ? "text-emerald-100/90 hover:bg-emerald-400/15 hover:text-emerald-50"
                  : "cursor-not-allowed text-slate-600"
              )}
            >
              {copiedMd ? (
                <Check className="h-4 w-4 text-emerald-300" aria-hidden />
              ) : (
                <Copy className="h-4 w-4" aria-hidden />
              )}
            </button>
            <span className="mx-0.5 h-4 w-px bg-emerald-400/20" aria-hidden />
            <button
              type="button"
              onClick={() => void downloadPdf()}
              disabled={!exportReady || pdfBusy}
              aria-label="Export as PDF"
              title="Export as PDF"
              className={cn(
                "rounded-md p-1.5 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-emerald-400/60",
                exportReady && !pdfBusy
                  ? "text-emerald-100/90 hover:bg-emerald-400/15 hover:text-emerald-50"
                  : "cursor-not-allowed text-slate-600"
              )}
            >
              {pdfBusy ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <FileDown className="h-4 w-4" aria-hidden />
              )}
            </button>
          </div>
          <Badge variant={status === "ERROR" ? "danger" : status === "COMPLETE" ? "success" : "default"}>
            {isStreaming && <Loader2 className="mr-1 h-3 w-3 animate-spin" />}
            {status}
          </Badge>
        </div>
      </div>

      <PhaseStepper activePhase={activePhase} />

      {exportReady ? (
        <div
          ref={pdfExportRef}
          className="pointer-events-none fixed left-[-14000px] top-0 z-0 w-[720px] bg-white px-10 py-8 prose prose-slate prose-sm max-w-none prose-headings:text-slate-900 prose-p:text-slate-800 prose-strong:text-slate-900 prose-a:text-sky-700 prose-code:bg-slate-100 prose-code:text-slate-900 prose-pre:bg-slate-100 prose-pre:text-slate-900"
          aria-hidden
        >
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{exportMarkdown}</ReactMarkdown>
        </div>
      ) : null}

      <div
        ref={scrollRef}
        onScroll={(event) => {
          shouldAutoScrollRef.current = isNearBottom(event.currentTarget);
        }}
        className="relative flex-1 space-y-4 overflow-y-auto overflow-x-hidden p-5 font-mono scrollbar-thin scrollbar-track-transparent scrollbar-thumb-slate-800/90 [scrollbar-color:rgba(30,41,59,0.9)_transparent] [scrollbar-width:thin] [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-track]:bg-transparent [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-slate-800/90 hover:[&::-webkit-scrollbar-thumb]:bg-slate-700"
      >
        <VerdictBar status={status} verdict={finalVerdict} tone={verdictTone} />

        {events.map((event) =>
          isDebateEvent(event) ? (
            <DebateBubble
              key={event.id}
              event={event}
              active={event.id === activeEventId}
              onAutoScrollTick={scheduleAutoScroll}
            />
          ) : (
            <TerminalLine
              key={event.id}
              event={event}
              active={event.id === activeEventId}
              onAutoScrollTick={scheduleAutoScroll}
            />
          )
        )}

        {isStreaming && (
          <div className="flex items-center gap-2 text-xs text-emerald-300/70">
            <RadioTower className="h-4 w-4 animate-pulse" />
            waiting for next LangGraph node...
          </div>
        )}
      </div>
    </Card>
  );
}

function VerdictBar({
  status,
  verdict,
  tone
}: {
  status: string;
  verdict: string;
  tone: VerdictTone;
}) {
  const toneClass =
    tone === "bullish"
      ? "border-emerald-400/35 bg-emerald-500/12 text-emerald-100 shadow-[0_0_28px_rgba(16,185,129,0.16)]"
      : tone === "bearish"
        ? "border-rose-400/35 bg-rose-500/12 text-rose-100 shadow-[0_0_28px_rgba(244,63,94,0.16)]"
        : tone === "neutral"
          ? "border-slate-400/25 bg-slate-500/12 text-slate-100"
          : "border-cyan-400/25 bg-cyan-400/10 text-cyan-100";

  return (
    <div className={cn("sticky top-0 z-10 -mx-1 rounded-2xl border px-4 py-3 backdrop-blur-md", toneClass)}>
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="font-mono text-[10px] uppercase tracking-[0.28em] text-current/55">
            Sticky Final Verdict
          </p>
          {status === "COMPLETE" && verdict ? (
            <p className="mt-1 truncate text-sm font-semibold">{verdict}</p>
          ) : (
            <p className="mt-1 animate-pulse bg-gradient-to-r from-cyan-200 via-emerald-200 to-cyan-200 bg-clip-text text-sm font-semibold text-transparent">
              Waiting for multi-agent consensus...
            </p>
          )}
        </div>
        <Badge variant={status === "COMPLETE" ? "success" : status === "ERROR" ? "danger" : "muted"}>
          {status}
        </Badge>
      </div>
    </div>
  );
}

function PhaseStepper({ activePhase }: { activePhase: ResearchPhase | null }) {
  const activeIdx = phaseIndex(activePhase);

  return (
    <div className="relative border-b border-cyan-400/10 bg-slate-950/70 px-5 py-4">
      <div className="pointer-events-none absolute inset-x-6 top-1/2 h-px bg-gradient-to-r from-cyan-400/15 via-emerald-300/20 to-rose-400/15" />
      <div className="relative grid grid-cols-3 gap-3">
        {PHASES.map((phase, index) => {
          const state = index < activeIdx ? "done" : index === activeIdx ? "active" : "pending";
          const isActive = state === "active";
          const isDone = state === "done";

          return (
            <div
              key={phase.id}
              className={cn(
                "relative rounded-2xl border px-3 py-3 backdrop-blur transition duration-300",
                isActive
                  ? "border-cyan-300/45 bg-cyan-400/10 shadow-[0_0_28px_rgba(34,211,238,0.16)]"
                  : isDone
                    ? "border-emerald-400/30 bg-emerald-400/[0.06] text-emerald-100"
                    : "border-slate-800/80 bg-black/25 text-slate-500"
              )}
            >
              <div className="flex items-center gap-3">
                <div
                  className={cn(
                    "relative flex h-8 w-8 shrink-0 items-center justify-center rounded-full border font-mono text-[11px] font-semibold",
                    isActive
                      ? "border-cyan-300 bg-cyan-300/15 text-cyan-100"
                      : isDone
                        ? "border-emerald-300/50 bg-emerald-400/10 text-emerald-100"
                        : "border-slate-700 bg-slate-950 text-slate-500"
                  )}
                >
                  {isActive ? (
                    <span className="absolute inset-0 animate-ping rounded-full border border-cyan-300/30" />
                  ) : null}
                  <span className="relative">{phase.step}</span>
                </div>
                <div className="min-w-0">
                  <p
                    className={cn(
                      "truncate font-mono text-xs uppercase tracking-[0.22em]",
                      isActive ? "text-cyan-100" : isDone ? "text-emerald-100" : "text-slate-500"
                    )}
                  >
                    {phase.title}
                  </p>
                  <p className="mt-1 truncate text-[10px] uppercase tracking-[0.2em] text-current/45">
                    {phase.caption}
                  </p>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function DebateBubble({
  event,
  active,
  onAutoScrollTick
}: {
  event: TerminalEvent;
  active: boolean;
  onAutoScrollTick: (behavior?: ScrollBehavior) => void;
}) {
  const [visibleMessage, setVisibleMessage] = useState("");
  const [visibleContent, setVisibleContent] = useState("");
  const lineMountTs = useRef<number | undefined>(event.ts);
  const side = debateSide(event);
  const isBull = side === "bull";
  const tsDisplay = formatFineTimestamp(event.ts ?? lineMountTs.current);

  useEffect(() => {
    lineMountTs.current = event.ts ?? Date.now();
  }, [event.id, event.ts]);

  useEffect(() => {
    let cancelled = false;
    const timers: number[] = [];
    const fullMessage = event.message ?? "";
    const fullContent = event.content ?? "";
    setVisibleMessage("");
    setVisibleContent("");

    const pushScroll = () => onAutoScrollTick("auto");
    let msgIdx = 0;
    const msgStep = Math.max(1, Math.ceil(fullMessage.length / 80));
    const msgTimer = window.setInterval(() => {
      if (cancelled) return;
      msgIdx = Math.min(fullMessage.length, msgIdx + msgStep);
      setVisibleMessage(fullMessage.slice(0, msgIdx));
      pushScroll();
      if (msgIdx >= fullMessage.length) {
        window.clearInterval(msgTimer);
        if (!fullContent || cancelled) return;
        let cIdx = 0;
        const cStep = Math.max(1, Math.ceil(fullContent.length / 220));
        const cTimer = window.setInterval(() => {
          if (cancelled) return;
          cIdx = Math.min(fullContent.length, cIdx + cStep);
          setVisibleContent(fullContent.slice(0, cIdx));
          pushScroll();
          if (cIdx >= fullContent.length) {
            window.clearInterval(cTimer);
          }
        }, 14);
        timers.push(cTimer);
      }
    }, 11);
    timers.push(msgTimer);

    return () => {
      cancelled = true;
      timers.forEach((timer) => window.clearInterval(timer));
    };
  }, [event.content, event.id, event.message, onAutoScrollTick]);

  return (
    <div className={cn("flex w-full", isBull ? "justify-start" : "justify-end")}>
      <div
        className={cn(
          "relative max-w-[86%] rounded-3xl border px-4 py-3 shadow-[0_18px_50px_rgba(0,0,0,0.28)] backdrop-blur",
          isBull
            ? "rounded-bl-md border-green-400/35 bg-green-950/30"
            : "rounded-br-md border-red-400/35 bg-red-950/30",
          active && (isBull ? "shadow-[0_0_30px_rgba(34,197,94,0.13)]" : "shadow-[0_0_30px_rgba(248,113,113,0.13)]")
        )}
      >
        <div
          className={cn(
            "mb-2 flex items-center gap-2",
            isBull ? "justify-start text-green-100" : "justify-end text-red-100"
          )}
        >
          {isBull ? <TrendingUp className="h-4 w-4" /> : null}
          <span className="font-mono text-[10px] tabular-nums text-current/60">[{tsDisplay}]</span>
          <span
            className={cn(
              "rounded-md border px-2 py-0.5 font-mono text-[11px] font-semibold uppercase tracking-[0.18em]",
              isBull
                ? "border-green-400/40 bg-green-400/10 text-green-100"
                : "border-red-400/40 bg-red-400/10 text-red-100"
            )}
          >
            {isBull ? "Bull Researcher" : "Bear Researcher"}
          </span>
          {!isBull ? <TrendingDown className="h-4 w-4" /> : null}
        </div>
        <p className={cn("text-sm leading-relaxed", isBull ? "text-green-50/90" : "text-red-50/90")}>
          {visibleMessage}
        </p>
        {event.content ? (
          <div
            className={cn(
              "prose prose-invert prose-sm mt-3 max-w-none prose-headings:text-current prose-a:text-cyan-300 prose-code:text-amber-200",
              isBull ? "text-green-50/85 prose-strong:text-green-100" : "text-red-50/85 prose-strong:text-red-100"
            )}
          >
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{visibleContent}</ReactMarkdown>
          </div>
        ) : null}
        {active ? (
          <div
            className={cn(
              "absolute top-3 h-2 w-2 animate-ping rounded-full",
              isBull ? "right-3 bg-green-300/70" : "left-3 bg-red-300/70"
            )}
          />
        ) : null}
      </div>
    </div>
  );
}

function TerminalLine({
  event,
  active,
  onAutoScrollTick
}: {
  event: TerminalEvent;
  active: boolean;
  onAutoScrollTick: (behavior?: ScrollBehavior) => void;
}) {
  const [visibleMessage, setVisibleMessage] = useState("");
  const [visibleContent, setVisibleContent] = useState("");
  const [open, setOpen] = useState(active || event.event === "start");
  const lineMountTs = useRef<number | undefined>(event.ts);
  const wasActiveRef = useRef(active);

  const isError = event.event === "error";
  const isComplete = event.event === "complete";
  const { skin: badgeSkin, badgeText } = resolveRolePresentation(event);

  const Icon = isError
    ? XCircle
    : isComplete
      ? CheckCircle2
      : event.stage === "debate"
        ? BrainCircuit
        : Bot;

  useEffect(() => {
    lineMountTs.current = event.ts ?? Date.now();
  }, [event.id, event.ts]);

  useEffect(() => {
    if (active) {
      setOpen(true);
    } else if (wasActiveRef.current) {
      setOpen(false);
    }
    wasActiveRef.current = active;
  }, [active]);

  useEffect(() => {
    let cancelled = false;
    const timers: number[] = [];

    const fullMessage = event.message ?? "";
    const fullContent = event.content ?? "";
    setVisibleMessage("");
    setVisibleContent("");

    const pushScroll = () => onAutoScrollTick("auto");

    let msgIdx = 0;
    const msgStep = Math.max(1, Math.ceil(fullMessage.length / 80));
    const msgTimer = window.setInterval(() => {
      if (cancelled) return;
      msgIdx = Math.min(fullMessage.length, msgIdx + msgStep);
      setVisibleMessage(fullMessage.slice(0, msgIdx));
      pushScroll();
      if (msgIdx >= fullMessage.length) {
        window.clearInterval(msgTimer);
        if (!fullContent || cancelled) return;
        let cIdx = 0;
        const cStep = Math.max(1, Math.ceil(fullContent.length / 220));
        const cTimer = window.setInterval(() => {
          if (cancelled) return;
          cIdx = Math.min(fullContent.length, cIdx + cStep);
          setVisibleContent(fullContent.slice(0, cIdx));
          pushScroll();
          if (cIdx >= fullContent.length) {
            window.clearInterval(cTimer);
          }
        }, 14);
        timers.push(cTimer);
      }
    }, 11);
    timers.push(msgTimer);

    return () => {
      cancelled = true;
      timers.forEach((t) => window.clearInterval(t));
    };
  }, [event.message, event.content, event.id, onAutoScrollTick]);

  const tsDisplay = formatFineTimestamp(event.ts ?? lineMountTs.current);
  const summaryTs = tsDisplay.split(".")[0] ?? tsDisplay;

  return (
    <Collapsible
      open={open}
      onOpenChange={setOpen}
      className={cn(
        "group rounded-2xl border bg-slate-950/70 transition hover:border-cyan-400/25",
        active ? "border-cyan-300/35 shadow-[0_0_24px_rgba(34,211,238,0.12)]" : "border-slate-800/80"
      )}
    >
      <CollapsibleTrigger asChild>
        <button
          type="button"
          className="flex w-full items-center gap-2 px-4 py-3 text-left focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-cyan-300/60"
        >
          {open ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-cyan-300 transition-transform" />
          ) : (
            <Plus className="h-3.5 w-3.5 shrink-0 text-emerald-300" />
          )}
          <span className="font-mono text-[10px] tabular-nums tracking-tight text-emerald-500/85">
            [{open ? tsDisplay : summaryTs}]
          </span>
          <span className={cn("inline-flex shrink-0 items-center font-mono", badgeSkin)}>{badgeText}</span>
          <span className="min-w-0 flex-1 truncate text-xs text-slate-300">
            {open ? event.message : `${summarizeEvent(event)} (点击展开)`}
          </span>
          {active ? (
            <span className="rounded-full border border-cyan-300/30 bg-cyan-300/10 px-2 py-0.5 text-[10px] uppercase tracking-[0.2em] text-cyan-100">
              Active
            </span>
          ) : null}
        </button>
      </CollapsibleTrigger>

      <CollapsibleContent className="px-4 pb-4">
        <div className="border-t border-slate-800/70 pt-3">
          <div className="mb-3 flex flex-wrap items-center gap-x-2 gap-y-1.5">
            <Icon
              className={cn(
                "h-4 w-4 shrink-0",
                isError ? "text-rose-300" : isComplete ? "text-cyan-300" : "text-sky-300"
              )}
            />
            {event.node && (
              <span className="text-[10px] text-slate-500">node:{event.node}</span>
            )}
          </div>
          <p className="text-sm leading-relaxed text-slate-300">{visibleMessage}</p>
          {event.content && (
            <div className="prose prose-invert prose-sm mt-3 max-w-none prose-headings:text-cyan-100 prose-a:text-cyan-300 prose-strong:text-emerald-200 prose-code:text-amber-200">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{visibleContent}</ReactMarkdown>
            </div>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

function isAbortError(err: unknown): boolean {
  if (typeof DOMException !== "undefined" && err instanceof DOMException) {
    return err.name === "AbortError";
  }
  return (
    typeof err === "object" &&
    err !== null &&
    "name" in err &&
    (err as { name: string }).name === "AbortError"
  );
}

async function streamResearch({
  ticker,
  depth,
  signal,
  onEvent,
  onAborted,
  onError
}: {
  ticker: string;
  depth: "quick" | "deep";
  signal: AbortSignal;
  onEvent: (event: TerminalEvent) => void;
  onAborted?: () => void;
  onError: (message: string) => void;
}) {
  try {
    const apiBase = getOpenFrApiBaseUrl();
    const response = await fetch(`${apiBase}/api/v1/research/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream"
      },
      body: JSON.stringify({ ticker, depth }),
      signal
    });

    if (!response.ok || !response.body) {
      onError(`HTTP ${response.status}: ${response.statusText}`);
      return;
    }

    const streamReader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    try {
      while (true) {
        const { value, done } = await streamReader.read();
        if (done) {
          const parsed = parseSseBlock(buffer.trim());
          if (parsed) {
            onEvent(toTerminalEvent(parsed));
          }
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() ?? "";

        for (const block of blocks) {
          const parsed = parseSseBlock(block);
          if (parsed) {
            onEvent(toTerminalEvent(parsed));
          }
        }
      }
    } finally {
      try {
        await streamReader.cancel();
      } catch {
        // ignore cancel/release errors
      }
    }
  } catch (err) {
    if (isAbortError(err)) {
      onAborted?.();
      return;
    }
    const message = err instanceof Error ? err.message : String(err);
    onError(message);
  }
}
