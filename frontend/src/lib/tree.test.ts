import { describe, expect, it } from "vitest";

import type { Span } from "./api";
import { buildTree, formatDuration, timelineBar, visibleNodes } from "./tree";

const s = (id: string, parent: string | null, start: number): Span => ({
  id,
  parent_id: parent,
  name: id,
  status: "ok",
  error: null,
  kind: "span",
  start_time: new Date(Date.UTC(2026, 0, 1, 0, 0, start)).toISOString(),
  end_time: null,
  input: null,
  output: null,
  metadata: null,
  model: null,
  input_tokens: null,
  output_tokens: null,
});

const shape = (nodes: ReturnType<typeof buildTree>): unknown =>
  nodes.map((n) => [n.span.id, n.depth, shape(n.children)]);

describe("buildTree", () => {
  it("nests by parent_id and orders siblings by start time", () => {
    const tree = buildTree([s("c2", "a", 3), s("c1", "a", 2), s("a", null, 1), s("g", "c1", 4)]);
    expect(shape(tree)).toEqual([["a", 0, [["c1", 1, [["g", 2, []]]], ["c2", 1, []]]]]);
  });

  it("keeps spans with a missing parent as roots", () => {
    const tree = buildTree([s("orphan", "gone", 2), s("root", null, 1)]);
    expect(tree.map((n) => n.span.id)).toEqual(["root", "orphan"]);
  });

  it("survives self-parents and cycles", () => {
    const tree = buildTree([s("self", "self", 1), s("x", "y", 2), s("y", "x", 3)]);
    expect(tree.map((n) => n.span.id)).toEqual(["self"]);
  });
});

describe("visibleNodes", () => {
  it("hides the descendants of collapsed nodes", () => {
    const tree = buildTree([s("a", null, 1), s("b", "a", 2), s("c", "b", 3), s("d", null, 4)]);
    const ids = (c: string[]) => visibleNodes(tree, new Set(c)).map((n) => n.span.id);
    expect(ids([])).toEqual(["a", "b", "c", "d"]);
    expect(ids(["b"])).toEqual(["a", "b", "d"]);
    expect(ids(["a"])).toEqual(["a", "d"]);
  });
});

describe("formatting", () => {
  it("formats durations", () => {
    expect(formatDuration(null)).toBe("—");
    expect(formatDuration(42)).toBe("42 ms");
    expect(formatDuration(1234)).toBe("1.23 s");
    expect(formatDuration(12_340)).toBe("12.3 s");
    expect(formatDuration(125_000)).toBe("2m 5s");
  });

  it("places spans on the timeline", () => {
    const t0 = Date.UTC(2026, 0, 1);
    const at = (sec: number) => new Date(t0 + sec * 1000).toISOString();
    expect(timelineBar({ start_time: at(1), end_time: at(3) }, t0, 4000)).toEqual({ left: 25, width: 50 });
    expect(timelineBar({ start_time: at(2), end_time: null }, t0, 4000)).toEqual({ left: 50, width: 0.5 });
    expect(timelineBar({ start_time: at(0), end_time: at(1) }, t0, 0)).toEqual({ left: 0, width: 100 });
  });
});
