import type { Span } from "./api";

export interface SpanNode {
  span: Span;
  depth: number;
  children: SpanNode[];
}

/** Spans (any order) -> forest ordered by start time. Spans whose parent is missing
 *  (not sent yet, or dropped) become roots, so nothing disappears. */
export function buildTree(spans: Span[]): SpanNode[] {
  const nodes = new Map(spans.map((s) => [s.id, { span: s, depth: 0, children: [] as SpanNode[] }]));
  const roots: SpanNode[] = [];
  for (const node of nodes.values()) {
    const parent = node.span.parent_id ? nodes.get(node.span.parent_id) : undefined;
    // A span can't be its own ancestor; treat a self-parent as a root.
    if (parent && parent !== node) parent.children.push(node);
    else roots.push(node);
  }
  const byStart = (a: SpanNode, b: SpanNode) => a.span.start_time.localeCompare(b.span.start_time);
  const visit = (list: SpanNode[], depth: number, seen: Set<SpanNode>) => {
    list.sort(byStart);
    for (const n of list) {
      if (seen.has(n)) continue; // guards against parent cycles in bad data
      seen.add(n);
      n.depth = depth;
      visit(n.children, depth + 1, seen);
    }
  };
  visit(roots, 0, new Set());
  return roots;
}

/** Depth-first list of the nodes that are visible given the collapsed set. */
export function visibleNodes(roots: SpanNode[], collapsed: Set<string>): SpanNode[] {
  const out: SpanNode[] = [];
  const walk = (list: SpanNode[]) => {
    for (const n of list) {
      out.push(n);
      if (!collapsed.has(n.span.id)) walk(n.children);
    }
  };
  walk(roots);
  return out;
}

export function durationMs(start: string, end: string | null): number | null {
  if (!end) return null;
  return new Date(end).getTime() - new Date(start).getTime();
}

export function formatDuration(ms: number | null): string {
  if (ms === null) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)} s`;
  const m = Math.floor(ms / 60_000);
  return `${m}m ${Math.round((ms % 60_000) / 1000)}s`;
}

/** Position of a span on the trace timeline, as percentages. */
export function timelineBar(
  span: { start_time: string; end_time: string | null },
  traceStart: number,
  traceMs: number,
): { left: number; width: number } {
  const start = new Date(span.start_time).getTime();
  const end = span.end_time ? new Date(span.end_time).getTime() : start;
  if (traceMs <= 0) return { left: 0, width: 100 };
  const left = Math.min(100, Math.max(0, ((start - traceStart) / traceMs) * 100));
  const width = Math.max(0.5, Math.min(100 - left, ((end - start) / traceMs) * 100));
  return { left, width };
}
