import { describe, expect, it, vi } from "vitest";

import {
  buildTerminalMarkdown,
  parseSseBlock,
  toTerminalEvent,
  type TerminalEvent
} from "./research-terminal-events";

describe("research-terminal-events", () => {
  it("parses JSON SSE blocks", () => {
    const parsed = parseSseBlock('event: agent_step\ndata: {"stage":"final","message":"done"}');

    expect(parsed).toEqual({
      event: "agent_step",
      data: { stage: "final", message: "done" }
    });
  });

  it("rejects unknown SSE event names", () => {
    expect(parseSseBlock('event: ping\ndata: {"ok":true}')).toBeNull();
  });

  it("parses plain-text SSE data as message", () => {
    const parsed = parseSseBlock("event: error\ndata: upstream failed");

    expect(parsed).toEqual({
      event: "error",
      data: { message: "upstream failed" }
    });
  });

  it("converts parsed SSE blocks into terminal events", () => {
    vi.spyOn(crypto, "randomUUID").mockReturnValue("event-1");
    vi.spyOn(Date, "now").mockReturnValue(1700000000000);

    const event = toTerminalEvent({
      event: "complete",
      data: { final_decision: "BUY" }
    });

    expect(event).toMatchObject({
      id: "event-1",
      event: "complete",
      label: "Report Generator",
      content: "BUY",
      ts: 1700000000000
    });
  });

  it("maps structured SSE error payloads into terminal error events", () => {
    vi.spyOn(crypto, "randomUUID").mockReturnValue("err-1");
    vi.spyOn(Date, "now").mockReturnValue(1700000000000);

    const event = toTerminalEvent({
      event: "error",
      data: {
        code: "STREAM_ERROR",
        message: "timeout",
        stage: "api",
        detail: "TimeoutError(...)"
      }
    });

    expect(event.event).toBe("error");
    expect(event.message).toBe("timeout");
    expect(event.content).toContain("code: STREAM_ERROR");
    expect(event.stage).toBe("api");
  });

  it("maps dashboard snapshots from SSE data", () => {
    vi.spyOn(crypto, "randomUUID").mockReturnValue("snapshot-1");
    vi.spyOn(Date, "now").mockReturnValue(1700000000000);

    const event = toTerminalEvent({
      event: "agent_step",
      data: {
        stage: "data_collection",
        node: "Fundamentals Analyst",
        message: "done",
        dashboard_snapshot: {
          ticker: "sh600519",
          code: "600519",
          updated_at: "2026-05-18T00:00:00",
          stale: false,
          source: "agent_snapshot",
          candles: [{ time: 1704067200, open: 1, high: 2, low: 0.5, close: 1.5 }],
          metrics: [{ label: "PE", value: "10.0x", trend: "flat" }],
          errors: []
        }
      }
    });

    expect(event.dashboardSnapshot?.source).toBe("agent_snapshot");
    expect(event.dashboardSnapshot?.candles[0]?.close).toBe(1.5);
  });

  it("builds export markdown from terminal events", () => {
    const events: TerminalEvent[] = [
      {
        id: "1",
        event: "complete",
        label: "Report",
        message: "done",
        content: "final text",
        ts: 1700000000000
      }
    ];

    const md = buildTerminalMarkdown(events, "600519", "quick", () => "[最终报告 Final Report]");

    expect(md).toContain("Ticker:** `600519`");
    expect(md).toContain("## [最终报告 Final Report]");
    expect(md).toContain("final text");
  });
});
