import { describe, expect, it } from "vitest";

import { type EvalRunDetail, compareRows, formatScore, questionOf, scorerNames } from "./evals";

const run = (scores: Record<string, number | null>, scorers: Record<string, number> = {}): EvalRunDetail =>
  ({
    summary: { scorers },
    results: Object.entries(scores).map(([key, score]) => ({
      item: { id: key, key, input: { question: `${key}?` }, expected: {} },
      score,
    })),
  }) as unknown as EvalRunDetail;

describe("compareRows", () => {
  it("joins by key and puts the biggest changes first, regressions before gains", () => {
    const a = run({ same: 1, worse: 1, better: 0.5, gone: 0.8 });
    const b = run({ same: 1, worse: 0.5, better: 1, added: 0.9 });
    const rows = compareRows(a, b);
    expect(rows.map((r) => [r.key, r.delta])).toEqual([
      ["worse", -0.5],
      ["better", 0.5],
      ["same", 0],
      ["added", null],
      ["gone", null],
    ]);
    expect(rows.find((r) => r.key === "added")?.a).toBeUndefined();
    expect(rows[0].question).toBe("worse?");
  });

  it("treats unscored items as no change", () => {
    const rows = compareRows(run({ x: null }), run({ x: 0.7 }));
    expect(rows[0].delta).toBeNull();
  });
});

describe("helpers", () => {
  it("formats scores", () => {
    expect(formatScore(0.904)).toBe("90%");
    expect(formatScore(null)).toBe("—");
    expect(formatScore(undefined)).toBe("—");
  });

  it("extracts the question", () => {
    expect(questionOf({ question: "Hi?" })).toBe("Hi?");
    expect(questionOf("plain")).toBe("plain");
    expect(questionOf({ q: 1 })).toBe('{"q":1}');
  });

  it("lists scorers across runs", () => {
    expect(scorerNames(run({}, { judge: 1, contains: 1 }), run({}, { tools: 1 }))).toEqual([
      "contains",
      "judge",
      "tools",
    ]);
  });
});
