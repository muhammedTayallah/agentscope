import { getJson } from "./api";

export interface Score {
  score: number | null;
  reason: string;
}

export interface Summary {
  items: number;
  answered: number;
  errors: number;
  score: number | null;
  pass_rate: number | null;
  scorers: Record<string, number>;
  avg_latency_ms: number | null;
  total_cost_usd: number | null;
}

export interface EvalRun {
  id: string;
  dataset_id: string;
  dataset_name: string;
  name: string;
  agent_version: string;
  status: "running" | "scoring" | "completed" | "failed";
  summary: Summary | null;
  error: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface Item {
  id: string;
  key: string;
  input: unknown;
  expected: { answer?: string; contains?: string[]; tools?: string[] };
}

export interface Result {
  item: Item;
  trace_id: string | null;
  output: string | null;
  error: string | null;
  scores: Record<string, Score> | null;
  score: number | null;
  latency_ms: number | null;
  cost_usd: number | null;
}

export interface EvalRunDetail extends EvalRun {
  results: Result[];
}

export const PASS_SCORE = 0.8; // same threshold as the server's pass rate

export const listEvalRuns = (projectId: string) => getJson<EvalRun[]>(`/projects/${projectId}/eval-runs`);
export const getEvalRun = (projectId: string, runId: string) =>
  getJson<EvalRunDetail>(`/projects/${projectId}/eval-runs/${runId}`);

export function formatScore(s: number | null | undefined): string {
  return s === null || s === undefined ? "—" : `${Math.round(s * 100)}%`;
}

export function questionOf(input: unknown): string {
  if (typeof input === "string") return input;
  if (input && typeof input === "object" && "question" in input) return String((input as { question: unknown }).question);
  return JSON.stringify(input);
}

export interface CompareRow {
  key: string;
  question: string;
  a: Result | undefined;
  b: Result | undefined;
  delta: number | null; // b.score - a.score
}

/** Join two runs' results by item key; biggest changes first (regressions before gains). */
export function compareRows(a: EvalRunDetail, b: EvalRunDetail): CompareRow[] {
  const byKey = new Map<string, CompareRow>();
  for (const [side, run] of [["a", a], ["b", b]] as const) {
    for (const r of run.results) {
      const row = byKey.get(r.item.key) ?? {
        key: r.item.key,
        question: questionOf(r.item.input),
        a: undefined,
        b: undefined,
        delta: null,
      };
      row[side] = r;
      byKey.set(r.item.key, row);
    }
  }
  const rows = [...byKey.values()];
  for (const row of rows) {
    const sa = row.a?.score;
    const sb = row.b?.score;
    row.delta = sa != null && sb != null ? sb - sa : null;
  }
  // Largest absolute change first; ties: regressions first, then key order. No delta last.
  return rows.sort(
    (x, y) =>
      Number(x.delta === null) - Number(y.delta === null) ||
      Math.abs(y.delta ?? 0) - Math.abs(x.delta ?? 0) ||
      (x.delta ?? 0) - (y.delta ?? 0) ||
      x.key.localeCompare(y.key),
  );
}

/** Scorer names present in either run, in a stable order. */
export function scorerNames(...runs: EvalRun[]): string[] {
  return [...new Set(runs.flatMap((r) => Object.keys(r.summary?.scorers ?? {})))].sort();
}
