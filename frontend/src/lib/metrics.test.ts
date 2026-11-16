import { describe, expect, it } from "vitest";

import { type Metrics, formatCost, formatCount, formatPercent, toChartRows } from "./metrics";

describe("formatting", () => {
  it("formats counts", () => {
    expect(formatCount(1284)).toBe("1,284");
    expect(formatCount(12_900)).toBe("12.9K");
    expect(formatCount(4_200_000)).toBe("4.2M");
  });

  it("formats costs with useful precision", () => {
    expect(formatCost(0)).toBe("$0");
    expect(formatCost(12.4)).toBe("$12.40");
    expect(formatCost(0.035)).toBe("$0.035");
    expect(formatCost(0.03555)).toBe("$0.036");
    expect(formatCost(0.00055)).toBe("$0.00055");
  });

  it("formats rates", () => {
    expect(formatPercent(null)).toBe("—");
    expect(formatPercent(1 / 3)).toBe("33%");
    expect(formatPercent(0.025)).toBe("2.5%");
    expect(formatPercent(0)).toBe("0%");
  });
});

describe("toChartRows", () => {
  it("splits runs into ok and errors and rounds latency", () => {
    const m = {
      bucket: "day",
      series: [
        { start: "2026-11-10T00:00:00Z", runs: 3, errors: 1, p50_ms: 200.4, p95_ms: 290.6, cost_usd: 0 },
        { start: "2026-11-11T00:00:00Z", runs: 0, errors: 0, p50_ms: null, p95_ms: null, cost_usd: 0 },
      ],
    } as Metrics;
    const rows = toChartRows(m);
    expect(rows.map(({ ok, errors, p50, p95 }) => [ok, errors, p50, p95])).toEqual([
      [2, 1, 200, 291],
      [0, 0, null, null],
    ]);
  });
});
