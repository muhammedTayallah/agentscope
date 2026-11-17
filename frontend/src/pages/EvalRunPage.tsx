import { Link, useParams } from "react-router-dom";

import { ScoreBadge } from "../components/ScoreBadge";
import { type Result, formatScore, getEvalRun, questionOf } from "../lib/evals";
import { formatCost } from "../lib/metrics";
import { formatDuration } from "../lib/tree";
import { useFetch } from "../lib/useFetch";
import { RunStatus } from "./EvalsPage";

export function EvalRunPage() {
  const { projectId = "", runId = "" } = useParams();
  const run = useFetch(() => getEvalRun(projectId, runId), [projectId, runId]);

  if (run.loading && !run.data) return <p className="text-sm text-slate-400">Loading eval run…</p>;
  if (run.error || !run.data) return <p className="text-sm text-red-600">{run.error?.message ?? "Not found."}</p>;
  const r = run.data;
  const s = r.summary;

  return (
    <div>
      <Link to={`/p/${projectId}/evals`} className="text-sm text-slate-500 hover:text-slate-900">
        ← All eval runs
      </Link>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">{r.name}</h1>
        {r.status === "completed" ? <ScoreBadge score={s?.score} /> : <RunStatus run={r} />}
      </div>
      <p className="mt-1 text-sm text-slate-500">
        Agent <span className="font-mono text-slate-700">{r.agent_version}</span> on dataset{" "}
        <span className="text-slate-700">{r.dataset_name}</span> · {new Date(r.created_at).toLocaleString()}
      </p>
      {s && (
        <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm text-slate-500">
          <Fact label="Pass rate" value={formatScore(s.pass_rate)} />
          {Object.entries(s.scorers).map(([k, v]) => (
            <Fact key={k} label={k} value={formatScore(v)} />
          ))}
          <Fact label="Answered" value={`${s.answered}/${s.items}`} />
          <Fact label="Agent errors" value={String(s.errors)} />
          <Fact label="Avg latency" value={formatDuration(s.avg_latency_ms)} />
          <Fact label="Cost" value={s.total_cost_usd != null ? formatCost(s.total_cost_usd) : "—"} />
        </dl>
      )}
      {r.error && <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{r.error}</p>}

      <ol className="mt-6 space-y-3" data-testid="eval-results">
        {r.results.map((res) => (
          <ResultCard key={res.item.key} result={res} projectId={projectId} />
        ))}
      </ol>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="inline">{label} </dt>
      <dd className="inline font-medium text-slate-800 tabular-nums">{value}</dd>
    </div>
  );
}

export function ResultCard({ result: res, projectId }: { result: Result; projectId: string }) {
  return (
    <li className="rounded-xl border border-slate-200 bg-white p-4" data-testid="eval-result">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-mono text-xs text-slate-500">{res.item.key}</p>
          <p className="font-medium text-slate-900">{questionOf(res.item.input)}</p>
        </div>
        <div className="flex items-center gap-3 text-xs text-slate-500">
          {res.latency_ms != null && <span>{formatDuration(res.latency_ms)}</span>}
          {res.cost_usd != null && <span>{formatCost(res.cost_usd)}</span>}
          {res.trace_id && (
            <Link to={`/p/${projectId}/runs/${res.trace_id}`} className="text-indigo-700 hover:underline">
              Trace →
            </Link>
          )}
          <ScoreBadge score={res.score} />
        </div>
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <div>
          <p className="text-xs font-medium tracking-wide text-slate-400 uppercase">Answer</p>
          {res.error ? (
            <p className="mt-1 font-mono text-xs text-red-700">{res.error}</p>
          ) : (
            <p className="mt-1 text-sm whitespace-pre-wrap text-slate-800">{res.output ?? "No answer submitted."}</p>
          )}
        </div>
        <div>
          <p className="text-xs font-medium tracking-wide text-slate-400 uppercase">Expected</p>
          <p className="mt-1 text-sm text-slate-600">{res.item.expected.answer ?? "—"}</p>
        </div>
      </div>
      {res.scores && Object.keys(res.scores).length > 0 && (
        <table className="mt-3 w-full text-left text-sm">
          <tbody className="divide-y divide-slate-100">
            {Object.entries(res.scores).map(([name, sc]) => (
              <tr key={name}>
                <td className="w-24 py-1.5 font-mono text-xs text-slate-500">{name}</td>
                <td className="w-32 py-1.5">
                  <ScoreBadge score={sc.score} />
                </td>
                <td className="py-1.5 text-xs text-slate-600">{sc.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </li>
  );
}
