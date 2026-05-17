import { parseMarketSnapshotPayload, type MarketSnapshot } from "../../lib/market-snapshot";

export type TerminalEvent = {
  id: string;
  event: "start" | "agent_step" | "complete" | "error";
  label: string;
  message: string;
  content: string;
  dashboardSnapshot?: MarketSnapshot;
  stage?: string;
  node?: string;
  /** Received time (ms since epoch) for fine-grained terminal timestamps */
  ts?: number;
};

/** Matches FastAPI SSE `event:` names from `/api/v1/research/stream`. */
export const SSE_EVENT_NAMES = ["start", "agent_step", "complete", "error"] as const;

export type SseEventName = (typeof SSE_EVENT_NAMES)[number];

export type SseBlock = {
  event: SseEventName;
  data: Record<string, unknown>;
};

export const stageLabels: Record<string, string> = {
  data_collection: "Data Fetcher",
  tool_call: "Tool Router",
  debate: "Bull/Bear Arena",
  synthesis: "Research Manager",
  risk_analysis: "Risk Council",
  final: "Report Generator",
  graph: "LangGraph"
};

export function formatFineTimestamp(ms: number | undefined): string {
  if (ms === undefined) {
    return "--:--:--.---";
  }
  const d = new Date(ms);
  const p = (n: number, len = 2) => String(n).padStart(len, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`;
}

function isSseEventName(value: string): value is SseEventName {
  return (SSE_EVENT_NAMES as readonly string[]).includes(value);
}

export function parseSseBlock(block: string): SseBlock | null {
  const lines = block.split("\n");
  const eventLine = lines.find((line) => line.startsWith("event:"));
  const dataLines = lines.filter((line) => line.startsWith("data:"));

  if (!eventLine || dataLines.length === 0) {
    return null;
  }

  const eventRaw = eventLine.replace("event:", "").trim();
  if (!isSseEventName(eventRaw)) {
    return null;
  }
  const event = eventRaw;
  const dataText = dataLines.map((line) => line.replace("data:", "").trim()).join("\n");

  try {
    const parsed: unknown = JSON.parse(dataText);
    const data =
      typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)
        ? (parsed as Record<string, unknown>)
        : { message: typeof parsed === "string" ? parsed : JSON.stringify(parsed) };
    return { event, data };
  } catch {
    return {
      event,
      data: { message: dataText }
    };
  }
}

export function toTerminalEvent(block: SseBlock): TerminalEvent {
  const data = block.data;

  if (block.event === "error") {
    const message = String(data.message ?? defaultMessage(block.event));
    const detail = typeof data.detail === "string" ? data.detail : "";
    const code = typeof data.code === "string" ? data.code : "";
    const contentParts = [message];
    if (code) contentParts.push(`code: ${code}`);
    if (detail && detail !== message) contentParts.push(detail);
    return {
      id: crypto.randomUUID(),
      event: "error",
      label: "Error",
      message,
      content: contentParts.join("\n\n"),
      stage: typeof data.stage === "string" ? data.stage : "graph",
      ts: Date.now()
    };
  }

  const stage = String(data.stage ?? "graph");
  const label = stageLabels[stage] ?? String(data.node ?? "Agent");
  const message = String(data.message ?? defaultMessage(block.event));
  const rawContent =
    data.content ??
    data.final_decision ??
    (block.event === "start" ? data.query : "") ??
    "";
  const dashboardSnapshot = parseOptionalDashboardSnapshot(data.dashboard_snapshot);

  return {
    id: crypto.randomUUID(),
    event: block.event,
    label: block.event === "start" ? "Orchestrator" : block.event === "complete" ? "Report Generator" : label,
    message,
    content: String(rawContent),
    dashboardSnapshot,
    stage,
    node: typeof data.node === "string" ? data.node : undefined,
    ts: Date.now()
  };
}

function parseOptionalDashboardSnapshot(raw: unknown): MarketSnapshot | undefined {
  if (raw === undefined || raw === null) {
    return undefined;
  }
  try {
    return parseMarketSnapshotPayload(raw);
  } catch {
    return undefined;
  }
}

export function buildTerminalMarkdown(
  events: TerminalEvent[],
  ticker: string,
  depth: string,
  resolveBadgeText: (event: TerminalEvent) => string
): string {
  const header = [
    `# OpenFR · Equity research transcript`,
    ``,
    `- **Ticker:** \`${ticker}\``,
    `- **Depth:** ${depth}`,
    `- **Exported (UTC):** ${new Date().toISOString()}`,
    ``,
    `---`,
    ``
  ].join("\n");

  const body = events
    .map((e) => {
      const badgeText = resolveBadgeText(e);
      const ts = formatFineTimestamp(e.ts);
      const meta = `_${ts}_ · **${e.label}** · \`${e.event}\`${e.node ? ` · node:\`${e.node}\`` : ""}`;
      const lines = [`## ${badgeText}`, ``, meta, ``, e.message.trim()];
      if (e.content?.trim()) {
        lines.push(``, e.content.trim());
      }
      return lines.join("\n");
    })
    .join("\n\n---\n\n");

  return `${header}${body}`;
}

function defaultMessage(event: TerminalEvent["event"]) {
  if (event === "start") {
    return "Research graph initialized.";
  }
  if (event === "complete") {
    return "Final investment report generated.";
  }
  if (event === "error") {
    return "Streaming pipeline failed.";
  }
  return "Agent step completed.";
}
