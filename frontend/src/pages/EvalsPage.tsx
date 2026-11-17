import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ScoreBadge } from "../components/ScoreBadge";
import { formatCost } from "../lib/metrics";
import { type EvalRun, formatScore, listEvalRuns, scorerNames } from "../lib/evals";
import { formatDuration } from "../lib/tree";
import { useFetch } from "../lib/useFetch";

export function EvalsPage() {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const runs = useFetch(() => listEvalRuns(projectId), [projectId]);
  const [picked, setPicked] = useState<string[]>([]);

  const all = runs.data ?? [];
  const scorers = scorerNames(...all);
  const pickedRuns = picked.map((id) => all.find((r) => r.id === id)).filter(Boolean) as EvalRun[];
  const sameDataset = pickedRuns.length === 2 && pickedRuns[0].dataset_id === pickedRuns[1].dataset_id;

  function toggle(id: string) {
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p.slice(-1), id]));
  }

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Evals</h1>
          <p className="mt-1 text-sm text-slate-500">
            Each run answers a dataset with one agent version. Select two runs of the same dataset to compare them.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button type="button" onClick={runs.reload} className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50">
            Refresh
          </button>
          <button
            type="button"
            disabled={!sameDataset}
            onClick={() => {
              // Older run on the left (A), newer on the right (B).
              const [a, b] = [...pickedRuns].sort((x, y) => x.created_at.localeCompare(y.created_at));
              navigate(`/p/${projectId}/evals/compare?a=${a.id}&b=${b.id}`);
            }}
            title={pickedRuns.length === 2 && !sameDataset ? "Pick two runs of the same dataset" : undefined}
            className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:bg-slate-200 disabled:text-slate-400"
          >
            Compare {picked.length}/2
          </button>
        </div>
      </div>

      <div className="mt-4 overflow-x-auto rounded-xl border border-slate-200 bg-white">
        <table className="w-full min-w-[860px] text-left text-sm" data-testid="eval-runs">
          <thead className="border-b border-slate-200 text-xs tracking-wide text-slate-500 uppercase">
            <tr>
              <th className="w-10 px-4 py-2.5" />
              <th className="px-2 py-2.5 font-medium">Run</th>
              <th className="px-2 py-2.5 font-medium">Agent version</th>
              <th className="px-2 py-2.5 font-medium">Dataset</th>
              <th className="px-2 py-2.5 font-medium">Score</th>
              <th className="px-2 py-2.5 text-right font-medium">Pass rate</th>
              {scorers.map((s) => (
                <th key={s} className="px-2 py-2.5 text-right font-medium">
                  {s}
                </th>
              ))}
              <th className="px-2 py-2.5 text-right font-medium">Avg latency</th>
              <th className="px-4 py-2.5 text-right font-medium">Cost</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {all.map((r) => (
              <tr key={r.id} className="hover:bg-slate-50" data-testid="eval-run-row">
                <td className="px-4 py-2.5">
                  <input
                    type="checkbox"
                    checked={picked.includes(r.id)}
                    onChange={() => toggle(r.id)}
                    aria-label={`Select ${r.name} to compare`}
                    className="size-4 accent-indigo-600"
                  />
                </td>
                <td className="px-2 py-2.5">
                  <Link to={`/p/${projectId}/evals/${r.id}`} className="font-medium text-indigo-700 hover:underline">
                    {r.name}
                  </Link>
                  <p className="text-xs text-slate-500">{new Date(r.created_at).toLocaleString()}</p>
                </td>
                <td className="px-2 py-2.5 font-mono text-xs">{r.agent_version}</td>
                <td className="px-2 py-2.5 text-slate-600">{r.dataset_name}</td>
                <td className="px-2 py-2.5">
                  {r.status === "completed" ? <ScoreBadge score={r.summary?.score} /> : <RunStatus run={r} />}
                </td>
                <td className="px-2 py-2.5 text-right tabular-nums">{formatScore(r.summary?.pass_rate)}</td>
                {scorers.map((s) => (
                  <td key={s} className="px-2 py-2.5 text-right tabular-nums">
                    {formatScore(r.summary?.scorers[s])}
                  </td>
                ))}
                <td className="px-2 py-2.5 text-right tabular-nums">{formatDuration(r.summary?.avg_latency_ms ?? null)}</td>
                <td className="px-4 py-2.5 text-right tabular-nums">
                  {r.summary?.total_cost_usd != null ? formatCost(r.summary.total_cost_usd) : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {runs.loading && !runs.data && <p className="px-4 py-6 text-sm text-slate-400">Loading…</p>}
        {runs.error && <p className="px-4 py-6 text-sm text-red-600">{runs.error.message}</p>}
        {runs.data?.length === 0 && (
          <div className="px-4 py-8 text-center text-sm text-slate-500">
            No eval runs yet. Run one from <code>evals/</code>:
            <pre className="mx-auto mt-3 w-fit rounded-lg bg-slate-900 px-3 py-2 text-left text-xs text-slate-100">
              uv run python -m agentscope_evals.experiment --version v1
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}

export function RunStatus({ run }: { run: EvalRun }) {
  const text = { running: "running…", scoring: "scoring…", failed: "failed", completed: "completed" }[run.status];
  return (
    <span className={`text-xs ${run.status === "failed" ? "text-red-700" : "text-slate-500"}`} title={run.error ?? undefined}>
      {text}
    </span>
  );
}
