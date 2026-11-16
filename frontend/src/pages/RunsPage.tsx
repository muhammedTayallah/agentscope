import { type FormEvent, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { StatusBadge } from "../components/StatusBadge";
import { listTraces } from "../lib/api";
import { durationMs, formatDuration } from "../lib/tree";
import { useFetch } from "../lib/useFetch";

const PAGE_SIZE = 50;

export function RunsPage() {
  const { projectId = "" } = useParams();
  // Filters live in the URL so they survive reloads and can be shared.
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const status = params.get("status") ?? "";
  const page = Math.max(0, Number(params.get("page") ?? 0) || 0);
  const [search, setSearch] = useState(q);

  const runs = useFetch(
    () => listTraces(projectId, { q, status, limit: PAGE_SIZE, offset: page * PAGE_SIZE }),
    [projectId, q, status, page],
  );

  function update(next: Record<string, string>) {
    const merged = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) {
      if (v) merged.set(k, v);
      else merged.delete(k);
    }
    setParams(merged);
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    update({ q: search.trim(), page: "" });
  }

  const total = runs.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Runs</h1>
        <form onSubmit={submit} className="flex flex-wrap items-center gap-2" role="search">
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name…"
            aria-label="Search runs by name"
            className="w-56 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm outline-none focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100"
          />
          <select
            aria-label="Status"
            value={status}
            onChange={(e) => update({ status: e.target.value, page: "" })}
            className="rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm"
          >
            <option value="">All statuses</option>
            <option value="ok">ok</option>
            <option value="error">error</option>
          </select>
          <button type="submit" className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700">
            Search
          </button>
          <button
            type="button"
            onClick={runs.reload}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
          >
            Refresh
          </button>
        </form>
      </div>

      <div className="mt-4 overflow-x-auto rounded-xl border border-slate-200 bg-white">
        <table className="w-full min-w-[640px] text-left text-sm" data-testid="runs-table">
          <thead className="border-b border-slate-200 text-xs tracking-wide text-slate-500 uppercase">
            <tr>
              <th className="px-4 py-2.5 font-medium">Name</th>
              <th className="px-4 py-2.5 font-medium">Status</th>
              <th className="px-4 py-2.5 font-medium">Started</th>
              <th className="px-4 py-2.5 text-right font-medium">Duration</th>
              <th className="px-4 py-2.5 text-right font-medium">Spans</th>
              <th className="px-4 py-2.5 text-right font-medium">Tokens (in / out)</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {runs.data?.items.map((t) => (
              <tr key={t.id} className="hover:bg-slate-50">
                <td className="px-4 py-2.5">
                  <Link to={`/p/${projectId}/runs/${t.id}`} className="font-medium text-indigo-700 hover:underline">
                    {t.name}
                  </Link>
                </td>
                <td className="px-4 py-2.5">
                  <StatusBadge status={t.status} />
                </td>
                <td className="px-4 py-2.5 whitespace-nowrap text-slate-600">
                  {new Date(t.start_time).toLocaleString()}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums">
                  {formatDuration(durationMs(t.start_time, t.end_time))}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums">{t.span_count}</td>
                <td className="px-4 py-2.5 text-right text-slate-600 tabular-nums">
                  {t.input_tokens.toLocaleString()} / {t.output_tokens.toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {runs.loading && !runs.data && <p className="px-4 py-6 text-sm text-slate-400">Loading…</p>}
        {runs.error && <p className="px-4 py-6 text-sm text-red-600">{runs.error.message}</p>}
        {runs.data?.items.length === 0 && (
          <p className="px-4 py-8 text-center text-sm text-slate-400">
            {q || status ? "No runs match these filters." : "No runs yet. Send a trace with the SDK."}
          </p>
        )}
      </div>

      <nav className="mt-3 flex items-center justify-between text-sm text-slate-500" aria-label="Pagination">
        <span>
          {total.toLocaleString()} run{total === 1 ? "" : "s"}
        </span>
        <span className="flex items-center gap-2">
          <button
            type="button"
            disabled={page === 0}
            onClick={() => update({ page: String(page - 1) })}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1 disabled:opacity-40"
          >
            Previous
          </button>
          Page {page + 1} of {pages}
          <button
            type="button"
            disabled={page + 1 >= pages}
            onClick={() => update({ page: String(page + 1) })}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1 disabled:opacity-40"
          >
            Next
          </button>
        </span>
      </nav>
    </div>
  );
}
