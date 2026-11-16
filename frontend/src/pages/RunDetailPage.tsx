import { useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { KindBadge, StatusBadge } from "../components/StatusBadge";
import { type Span, type TraceDetail, getTrace } from "../lib/api";
import { buildTree, durationMs, formatDuration, timelineBar, visibleNodes } from "../lib/tree";
import { useFetch } from "../lib/useFetch";

export function RunDetailPage() {
  const { projectId = "", traceId = "" } = useParams();
  const trace = useFetch(() => getTrace(projectId, traceId), [projectId, traceId]);

  if (trace.loading && !trace.data) return <p className="text-sm text-slate-400">Loading run…</p>;
  if (trace.error || !trace.data) {
    return <p className="text-sm text-red-600">{trace.error?.message ?? "Run not found."}</p>;
  }
  return <RunView trace={trace.data} projectId={projectId} />;
}

function RunView({ trace, projectId }: { trace: TraceDetail; projectId: string }) {
  // The selected span lives in the URL (?span=id) so a link opens the same view.
  const [params, setParams] = useSearchParams();
  const selectedId = params.get("span");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const roots = useMemo(() => buildTree(trace.spans), [trace.spans]);
  const rows = visibleNodes(roots, collapsed);
  const selected = trace.spans.find((s) => s.id === selectedId) ?? null;

  // Timeline spans the trace, or the spans themselves when the trace has no end yet.
  const traceStart = new Date(trace.start_time).getTime();
  const lastEnd = Math.max(
    trace.end_time ? new Date(trace.end_time).getTime() : 0,
    ...trace.spans.map((s) => (s.end_time ? new Date(s.end_time).getTime() : 0)),
  );
  const traceMs = Math.max(0, lastEnd - traceStart);
  const tokens = trace.spans.reduce(
    (acc, s) => [acc[0] + (s.input_tokens ?? 0), acc[1] + (s.output_tokens ?? 0)],
    [0, 0],
  );

  function select(id: string | null) {
    const next = new URLSearchParams(params);
    if (id) next.set("span", id);
    else next.delete("span");
    setParams(next, { replace: true });
  }

  function toggle(id: string) {
    setCollapsed((c) => {
      const next = new Set(c);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div>
      <Link to={`/p/${projectId}/runs`} className="text-sm text-slate-500 hover:text-slate-900">
        ← All runs
      </Link>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight" data-testid="run-name">
          {trace.name}
        </h1>
        <StatusBadge status={trace.status} />
      </div>
      <dl className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-sm text-slate-500">
        <div>
          <dt className="inline">Started </dt>
          <dd className="inline text-slate-700">{new Date(trace.start_time).toLocaleString()}</dd>
        </div>
        <div>
          <dt className="inline">Duration </dt>
          <dd className="inline text-slate-700">{formatDuration(durationMs(trace.start_time, trace.end_time))}</dd>
        </div>
        <div>
          <dt className="inline">Spans </dt>
          <dd className="inline text-slate-700">{trace.spans.length}</dd>
        </div>
        <div>
          <dt className="inline">Tokens </dt>
          <dd className="inline text-slate-700">
            {tokens[0].toLocaleString()} in / {tokens[1].toLocaleString()} out
          </dd>
        </div>
      </dl>
      {trace.error && <ErrorBox message={trace.error} />}

      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <section className="rounded-xl border border-slate-200 bg-white" aria-label="Span tree">
          <button
            type="button"
            onClick={() => select(null)}
            aria-pressed={!selected}
            className={`flex w-full items-center gap-2 border-b border-slate-100 px-4 py-2.5 text-left text-sm ${!selected ? "bg-indigo-50" : "hover:bg-slate-50"}`}
          >
            <span className="font-semibold">{trace.name}</span>
            <span className="text-slate-400">· trace</span>
          </button>
          {rows.length === 0 && <p className="px-4 py-6 text-sm text-slate-400">This run has no spans.</p>}
          <ul role="tree" aria-label="Spans" data-testid="span-tree">
            {rows.map(({ span, depth, children }) => {
              const bar = timelineBar(span, traceStart, traceMs);
              const isOpen = !collapsed.has(span.id);
              const isSelected = span.id === selectedId;
              return (
                <li
                  key={span.id}
                  role="treeitem"
                  aria-level={depth + 1}
                  aria-selected={isSelected}
                  aria-expanded={children.length ? isOpen : undefined}
                  data-testid="span-row"
                  data-depth={depth}
                  className={`flex items-center gap-2 border-b border-slate-50 pr-4 text-sm ${isSelected ? "bg-indigo-50" : "hover:bg-slate-50"}`}
                  style={{ paddingLeft: 12 + depth * 20 }}
                >
                  <button
                    type="button"
                    onClick={() => toggle(span.id)}
                    disabled={!children.length}
                    aria-label={isOpen ? `Collapse ${span.name}` : `Expand ${span.name}`}
                    className="w-4 shrink-0 text-slate-400 disabled:invisible"
                  >
                    {isOpen ? "▾" : "▸"}
                  </button>
                  <button
                    type="button"
                    onClick={() => select(span.id)}
                    className="flex min-w-0 flex-1 items-center gap-2 py-2 text-left"
                  >
                    <KindBadge kind={span.kind} />
                    <span className={`truncate ${span.status === "error" ? "text-red-700" : ""}`}>{span.name}</span>
                    <span className="relative ml-auto hidden h-2 w-40 shrink-0 rounded bg-slate-100 sm:block" aria-hidden>
                      <span
                        className={`absolute inset-y-0 rounded ${span.status === "error" ? "bg-red-400" : span.kind === "llm" ? "bg-violet-400" : span.kind === "tool" ? "bg-amber-400" : "bg-slate-400"}`}
                        style={{ left: `${bar.left}%`, width: `${bar.width}%` }}
                      />
                    </span>
                    <span className="w-16 shrink-0 text-right text-xs text-slate-500 tabular-nums">
                      {formatDuration(durationMs(span.start_time, span.end_time))}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </section>

        <section
          className="self-start rounded-xl border border-slate-200 bg-white p-5 lg:sticky lg:top-20"
          aria-label="Details"
          data-testid="details"
        >
          {selected ? <SpanDetails span={selected} /> : <TraceDetails trace={trace} />}
        </section>
      </div>
    </div>
  );
}

function SpanDetails({ span }: { span: Span }) {
  return (
    <div>
      <div className="flex items-center gap-2">
        <KindBadge kind={span.kind} />
        <h2 className="truncate text-lg font-semibold" data-testid="details-name">
          {span.name}
        </h2>
        <StatusBadge status={span.status} />
      </div>
      <Facts
        rows={[
          ["Duration", formatDuration(durationMs(span.start_time, span.end_time))],
          ["Started", new Date(span.start_time).toLocaleTimeString()],
          ["Model", span.model],
          ["Input tokens", span.input_tokens?.toLocaleString()],
          ["Output tokens", span.output_tokens?.toLocaleString()],
        ]}
      />
      {span.error && <ErrorBox message={span.error} />}
      <Json label="Input" value={span.input} />
      <Json label="Output" value={span.output} />
      <Json label="Metadata" value={span.metadata} />
    </div>
  );
}

function TraceDetails({ trace }: { trace: TraceDetail }) {
  return (
    <div>
      <h2 className="text-lg font-semibold" data-testid="details-name">
        {trace.name}
      </h2>
      <p className="text-sm text-slate-500">Whole run. Select a span to see its details.</p>
      <Json label="Input" value={trace.input} />
      <Json label="Output" value={trace.output} />
      <Json label="Metadata" value={trace.metadata} />
    </div>
  );
}

function Facts({ rows }: { rows: [string, string | null | undefined][] }) {
  const shown = rows.filter(([, v]) => v != null && v !== "");
  return (
    <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
      {shown.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-slate-500">{k}</dt>
          <dd className="text-slate-800 tabular-nums">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function Json({ label, value }: { label: string; value: unknown }) {
  if (value === null || value === undefined) return null;
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return (
    <div className="mt-4">
      <h3 className="text-xs font-medium tracking-wide text-slate-400 uppercase">{label}</h3>
      <pre
        data-testid={`details-${label.toLowerCase()}`}
        className="mt-1 max-h-80 overflow-auto rounded-lg bg-slate-50 p-3 text-xs leading-relaxed whitespace-pre-wrap break-words text-slate-800 ring-1 ring-slate-200"
      >
        {text}
      </pre>
    </div>
  );
}

function ErrorBox({ message }: { message: string }) {
  return (
    <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 font-mono text-xs whitespace-pre-wrap text-red-700 ring-1 ring-red-200">
      {message}
    </p>
  );
}
