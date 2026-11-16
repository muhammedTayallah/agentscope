import { getJson } from "./api";

export type Bucket = "hour" | "day";

export interface ModelUsage {
  model: string | null;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number | null;
}

export interface Point {
  start: string;
  runs: number;
  errors: number;
  p50_ms: number | null;
  p95_ms: number | null;
  cost_usd: number;
}

export interface Metrics {
  start: string;
  end: string;
  bucket: Bucket;
  runs: number;
  errors: number;
  error_rate: number | null;
  p50_ms: number | null;
  p95_ms: number | null;
  p99_ms: number | null;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  unpriced_models: string[];
  by_model: ModelUsage[];
  series: Point[];
}

export const RANGES = {
  "24h": { label: "Last 24 hours", hours: 24 },
  "7d": { label: "Last 7 days", hours: 24 * 7 },
  "30d": { label: "Last 30 days", hours: 24 * 30 },
} as const;
export type RangeKey = keyof typeof RANGES;

export function getMetrics(projectId: string, range: RangeKey, now = new Date()) {
  const start = new Date(now.getTime() - RANGES[range].hours * 3_600_000);
  const qs = new URLSearchParams({ start: start.toISOString(), end: now.toISOString() });
  return getJson<Metrics>(`/projects/${projectId}/metrics?${qs}`);
}

// ---------- Formatting (tested) ----------

const compact = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });

/** 1,284 / 12.9K / 4.2M: full under 10,000, compact above. */
export function formatCount(n: number): string {
  return n < 10_000 ? n.toLocaleString("en") : compact.format(n);
}

/** Dollars with enough precision for tiny LLM costs: $12.40, $0.035, $0.00055. */
export function formatCost(usd: number): string {
  if (usd === 0) return "$0";
  if (usd >= 1) return `$${usd.toFixed(2)}`;
  return `$${Number(usd.toPrecision(2))}`;
}

export function formatPercent(rate: number | null): string {
  if (rate === null) return "—";
  return `${(rate * 100).toFixed(rate > 0 && rate < 0.1 ? 1 : 0)}%`;
}

/** Axis/tooltip label for a bucket start, in the viewer's time zone. */
export function bucketLabel(iso: string, bucket: Bucket): string {
  const d = new Date(iso);
  return bucket === "hour"
    ? d.toLocaleString("en", { month: "short", day: "numeric", hour: "numeric" })
    : d.toLocaleDateString("en", { month: "short", day: "numeric" });
}

/** Chart rows: successful runs and errors stacked, latency as two lines. */
export function toChartRows(m: Metrics) {
  return m.series.map((p) => ({
    label: bucketLabel(p.start, m.bucket),
    ok: p.runs - p.errors,
    errors: p.errors,
    p50: p.p50_ms === null ? null : Math.round(p.p50_ms),
    p95: p.p95_ms === null ? null : Math.round(p.p95_ms),
  }));
}
