import { Link, useParams, useSearchParams } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Delta, ScoreBadge } from "../components/ScoreBadge";
import { type EvalRunDetail, compareRows, formatScore, getEvalRun, scorerNames } from "../lib/evals";
import { formatCost } from "../lib/metrics";
import { formatDuration } from "../lib/tree";
import { useFetch } from "../lib/useFetch";

// Validated pair (dataviz validator, white surface): series blue / series orange.
const A_COLOR = "#2a78d6";
const B_COLOR = "#eb6834";

export function EvalComparePage() {
  const { projectId = "" } = useParams();
  const [params] = useSearchParams();
  const aId = params.get("a") ?? "";
  const bId = params.get("b") ?? "";
  const runs = useFetch(
    () => Promise.all([getEvalRun(projectId, aId), getEvalRun(projectId, bId)]),
    [projectId, aId, bId],
  );

  if (runs.loading && !runs.data) return <p className="text-sm text-slate-400">Loading runs…</p>;
  if (runs.error || !runs.data) return <p className="text-sm text-red-600">{runs.error?.message ?? "Not found."}</p>;
  const [a, b] = runs.data;
  if (a.dataset_id !== b.dataset_id) return <p className="text-sm text-red-600">These runs use different datasets.</p>;
  return <Compare a={a} b={b} projectId={projectId} />;
}

function Compare({ a, b, projectId }: { a: EvalRunDetail; b: EvalRunDetail; projectId: string }) {
  const rows = compareRows(a, b);
  const scorers = scorerNames(a, b);
  const chart = ["overall", ...scorers].map((name) => ({
    name,
    a: (name === "overall" ? a.summary?.score : a.summary?.scorers[name]) ?? null,
    b: (name === "overall" ? b.summary?.score : b.summary?.scorers[name]) ?? null,
  }));
  const pct = (v: number | null) => (v === null ? null : Math.round(v * 100));
  const changed = rows.filter((r) => r.delta !== null && Math.round(r.delta * 100) !== 0).length;

  const summaryRows: [string, string, string, number | null][] = [
    ["Overall score", formatScore(a.summary?.score), formatScore(b.summary?.score), diff(a.summary?.score, b.summary?.score)],
    ["Pass rate", formatScore(a.summary?.pass_rate), formatScore(b.summary?.pass_rate), diff(a.summary?.pass_rate, b.summary?.pass_rate)],
    ...scorers.map(
      (s) =>
        [s, formatScore(a.summary?.scorers[s]), formatScore(b.summary?.scorers[s]), diff(a.summary?.scorers[s], b.summary?.scorers[s])] as [
          string,
          string,
          string,
          number | null,
        ],
    ),
  ];

  return (
    <div>
      <Link to={`/p/${projectId}/evals`} className="text-sm text-slate-500 hover:text-slate-900">
        ← All eval runs
      </Link>
      <h1 className="mt-2 text-2xl font-semibold tracking-tight">Compare eval runs</h1>
      <p className="mt-1 text-sm text-slate-500">
        Dataset <span className="text-slate-700">{a.dataset_name}</span> · {rows.length} items · {changed} changed
      </p>

      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <section className="rounded-xl border border-slate-200 bg-white p-4" aria-label="Summary">
          <table className="w-full text-left text-sm" data-testid="compare-summary">
            <thead className="text-xs tracking-wide text-slate-500 uppercase">
              <tr>
                <th className="py-2 font-medium" />
                <RunHead run={a} label="A" color={A_COLOR} />
                <RunHead run={b} label="B" color={B_COLOR} />
                <th className="py-2 text-right font-medium">B − A</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 tabular-nums">
              {summaryRows.map(([label, va, vb, d]) => (
                <tr key={label}>
                  <td className="py-2 text-slate-600">{label}</td>
                  <td className="py-2 text-right">{va}</td>
                  <td className="py-2 text-right">{vb}</td>
                  <td className="py-2 text-right">
                    <Delta value={d} />
                  </td>
                </tr>
              ))}
              <tr>
                <td className="py-2 text-slate-600">Avg latency</td>
                <td className="py-2 text-right">{formatDuration(a.summary?.avg_latency_ms ?? null)}</td>
                <td className="py-2 text-right">{formatDuration(b.summary?.avg_latency_ms ?? null)}</td>
                <td />
              </tr>
              <tr>
                <td className="py-2 text-slate-600">Cost</td>
                <td className="py-2 text-right">{a.summary?.total_cost_usd != null ? formatCost(a.summary.total_cost_usd) : "—"}</td>
                <td className="py-2 text-right">{b.summary?.total_cost_usd != null ? formatCost(b.summary.total_cost_usd) : "—"}</td>
                <td />
              </tr>
            </tbody>
          </table>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-4" aria-label="Scores by scorer">
          <h2 className="font-semibold">Scores by scorer</h2>
          <p className="mb-2 text-xs text-slate-500">Average score per scorer, A vs B (%)</p>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={chart.map((c) => ({ ...c, a: pct(c.a), b: pct(c.b) }))} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
              <CartesianGrid vertical={false} stroke="#e1e0d9" />
              <XAxis dataKey="name" stroke="#898781" fontSize={12} tickLine={false} axisLine={{ stroke: "#c3c2b7" }} />
              <YAxis domain={[0, 100]} stroke="#898781" fontSize={12} tickLine={false} axisLine={false} width={48} />
              <Tooltip
                itemStyle={{ color: "#0b0b0b" }}
                labelStyle={{ color: "#52514e", fontWeight: 600 }}
                contentStyle={{ borderRadius: 8, borderColor: "#e1e0d9", fontSize: 12 }}
                formatter={(v) => `${v}%`}
                cursor={{ fill: "rgba(11,11,11,0.04)" }}
              />
              <Legend iconType="circle" formatter={(v: string) => <span style={{ color: "#52514e" }}>{v}</span>} wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="a" name={`A · ${a.agent_version}`} fill={A_COLOR} maxBarSize={24} radius={[4, 4, 0, 0]} stroke="#ffffff" strokeWidth={2} />
              <Bar dataKey="b" name={`B · ${b.agent_version}`} fill={B_COLOR} maxBarSize={24} radius={[4, 4, 0, 0]} stroke="#ffffff" strokeWidth={2} />
            </BarChart>
          </ResponsiveContainer>
        </section>
      </div>

      <div className="mt-6 overflow-x-auto rounded-xl border border-slate-200 bg-white">
        <table className="w-full min-w-[900px] text-left text-sm" data-testid="compare-items">
          <thead className="border-b border-slate-200 text-xs tracking-wide text-slate-500 uppercase">
            <tr>
              <th className="px-4 py-2.5 font-medium">Item</th>
              <th className="px-2 py-2.5 font-medium">A · {a.agent_version}</th>
              <th className="px-2 py-2.5 font-medium">B · {b.agent_version}</th>
              <th className="px-4 py-2.5 text-right font-medium">Change</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 align-top">
            {rows.map((row) => (
              <tr key={row.key} data-testid="compare-row">
                <td className="w-64 px-4 py-3">
                  <p className="font-mono text-xs text-slate-500">{row.key}</p>
                  <p className="text-slate-800">{row.question}</p>
                </td>
                {[row.a, row.b].map((res, i) => (
                  <td key={i} className="px-2 py-3">
                    <ScoreBadge score={res?.score} />
                    <p className="mt-1 text-xs whitespace-pre-wrap text-slate-600">
                      {res ? (res.error ? `Error: ${res.error}` : (res.output ?? "No answer.")) : "Not in this run."}
                    </p>
                    {res?.scores &&
                      Object.entries(res.scores)
                        .filter(([, sc]) => sc.score !== null && sc.score < 1)
                        .map(([name, sc]) => (
                          <p key={name} className="mt-1 text-xs text-slate-500">
                            <span className="font-mono">{name}</span> {formatScore(sc.score)}: {sc.reason}
                          </p>
                        ))}
                  </td>
                ))}
                <td className="px-4 py-3 text-right">
                  <Delta value={row.delta} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RunHead({ run, label, color }: { run: EvalRunDetail; label: string; color: string }) {
  return (
    <th className="py-2 text-right font-medium normal-case">
      <span className="inline-flex items-center gap-1.5">
        <span className="size-2 rounded-full" style={{ background: color }} aria-hidden />
        {label} · <span className="font-mono">{run.agent_version}</span>
      </span>
    </th>
  );
}

function diff(x: number | null | undefined, y: number | null | undefined): number | null {
  return x == null || y == null ? null : y - x;
}
