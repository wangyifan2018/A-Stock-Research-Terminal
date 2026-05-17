import { describe, expect, it } from "vitest";

import { parseMarketSnapshotPayload } from "./market-snapshot";

describe("parseMarketSnapshotPayload", () => {
  it("accepts a valid snapshot shape", () => {
    const parsed = parseMarketSnapshotPayload({
      ticker: "sh600519",
      code: "600519",
      updated_at: "2026-05-18T12:00:00",
      stale: false,
      source: "agent_snapshot",
      candles: [{ time: 1704067200, open: 1, high: 2, low: 0.5, close: 1.5 }],
      metrics: [{ label: "PE", value: "10x" }],
      errors: []
    });

    expect(parsed.ticker).toBe("sh600519");
    expect(parsed.source).toBe("agent_snapshot");
    expect(parsed.candles).toHaveLength(1);
    expect(parsed.metrics).toHaveLength(1);
  });

  it("rejects non-objects", () => {
    expect(() => parseMarketSnapshotPayload(null)).toThrow();
    expect(() => parseMarketSnapshotPayload([])).toThrow();
  });
});
