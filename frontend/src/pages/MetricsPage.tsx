import type { ReactNode } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  type Metrics,
  RANGES,
  type RangeKey,
  bucketLabel,
  formatCost,
  formatCount,
  formatPercent,
  getMetrics,
  toChartRows,
} from "../lib/metrics";
import { formatDuration } from "../lib/tree";
import { useFetch } from "../lib/useFetch";

// Validated pairs (dataviz validator, white surface): blue/critical-red and blue/orange.
const C = {
  ok: "#2a78d6", // series 1
  p95: "#eb6834", // series 2
  error: "#d03b3b", // status: critical
  grid: "#e1e0d9",
  axis: "#898781",
  surface: "#ffffff",
};
const AXIS = { stroke: C.axis, fontSize: 12, tickLine: false, axisLine: { stroke: "#c3c2b7" } };
// Text stays in ink colours; the swatch beside it carries the series colour.
const TOOLTIP = {
  itemStyle: { color: "#0b0b0b" },
  labelStyle: { color: "#52514e", fontWeight: 600 },
  contentStyle: { borderRadius: 8, borderColor: "#e1e0d9", fontSize: 12 },
};
const legendText = (value: string) => <span style={{ color: "#52514e" }}>{value}</span>;
const dot = (color: string) => ({ r: 4, fill: color, stroke: C.surface, strokeWidth: 2 });

export function MetricsPage() {
  const { projectId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const range = (params.get("range") as RangeKey) in RANGES ? (params.get("range") as RangeKey) : "7d";
  const metrics = useFetch(() => getMetrics(projectId, range), [projectId, range]);

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Metrics</h1>
        <div role="group" aria-label="Time range" className="flex rounded-lg border border-slate-300 bg-white p-0.5 text-sm">
          {(Object.keys(RANGES) as RangeKey[]).map((key) => (
            <button
              key={key}
              type="button"
              aria-pressed={key === range}
              onClick={() => setParams({ range: key })}
              className={`rounded-md px-3 py-1 ${key === range ? "bg-indigo-600 font-medium text-white" : "text-slate-600 hover:bg-slate-100"}`}
            >
              {RANGES[key].label}
            </button>
          ))}
        </div>
      </div>

      {metrics.error && <p className="mt-6 text-sm text-red-600">{metrics.error.message}</p>}
      {metrics.loading && !metrics.data && <p className="mt-6 text-sm text-slate-400">Loading metrics…</p>}
      {metrics.data && <MetricsView m={metrics.data} />}
    </div>
  );
}

function MetricsView({ m }: { m: Metrics }) {
  const rows = toChartRows(m);
  const per = m.bucket === "hour" ? "hour" : "day";
  const priced = m.by_model.filter((u) => u.cost_usd !== null && u.cost_usd > 0);

  return (
    <>
      <section className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6" aria-label="Summary">
        <Tile label="Runs" value={formatCount(m.runs)} />
        <Tile label="Error rate" value={formatPercent(m.error_rate)} sub={`${formatCount(m.errors)} failed`} />
        <Tile label="Latency p50" value={formatDuration(m.p50_ms)} />
        <Tile label="Latency p95" value={formatDuration(m.p95_ms)} sub={`p99 ${formatDuration(m.p99_ms)}`} />
        <Tile
          label="Tokens"
          value={formatCount(m.input_tokens + m.output_tokens)}
          sub={`${formatCount(m.input_tokens)} in · ${formatCount(m.output_tokens)} out`}
        />
        <Tile
          label="Cost"
          value={formatCost(m.cost_usd)}
          sub={m.unpriced_models.length ? `+ ${m.unpriced_models.length} unpriced model(s)` : undefined}
        />
      </section>

      {m.runs === 0 && (
        <p className="mt-6 rounded-xl border border-dashed border-slate-300 bg-white px-4 py-8 text-center text-sm text-slate-500">
          No runs in this period.
        </p>
      )}

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Card title={`Runs per ${per}`} subtitle="Successful and failed runs, by start time">
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
              <CartesianGrid vertical={false} stroke={C.grid} />
              <XAxis dataKey="label" {...AXIS} minTickGap={16} />
              <YAxis {...AXIS} allowDecimals={false} width={48} />
              <Tooltip {...TOOLTIP} cursor={{ fill: "rgba(11,11,11,0.04)" }} />
              <Legend iconType="circle" formatter={legendText} wrapperStyle={{ fontSize: 12 }} />
              {/* 2px surface-coloured stroke = the gap between stacked segments */}
              <Bar dataKey="ok" name="Succeeded" stackId="runs" fill={C.ok} stroke={C.surface} strokeWidth={2} maxBarSize={24} />
              <Bar
                dataKey="errors"
                name="Failed"
                stackId="runs"
                fill={C.error}
                stroke={C.surface}
                strokeWidth={2}
                maxBarSize={24}
                radius={[4, 4, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Latency" subtitle={`Run duration per ${per}, p50 and p95 (ms)`}>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -4 }}>
              <CartesianGrid vertical={false} stroke={C.grid} />
              <XAxis dataKey="label" {...AXIS} minTickGap={16} />
              <YAxis {...AXIS} width={56} tickFormatter={(v: number) => formatCount(v)} />
              <Tooltip {...TOOLTIP} formatter={(v) => (typeof v === "number" ? formatDuration(v) : v)} />
              <Legend iconType="plainline" formatter={legendText} wrapperStyle={{ fontSize: 12 }} />
              <Line dataKey="p50" name="p50" stroke={C.ok} strokeWidth={2} dot={dot(C.ok)} activeDot={dot(C.ok)} />
              <Line dataKey="p95" name="p95" stroke={C.p95} strokeWidth={2} dot={dot(C.p95)} activeDot={dot(C.p95)} />
            </LineChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Cost by model" subtitle="Priced LLM calls in this period (USD)">
          {priced.length === 0 ? (
            <p className="py-10 text-center text-sm text-slate-400">No priced model usage in this period.</p>
          ) : (
            <ResponsiveContainer width="100%" height={Math.max(120, priced.length * 44 + 24)}>
              <BarChart data={priced} layout="vertical" margin={{ top: 0, right: 64, bottom: 0, left: 8 }}>
                <XAxis type="number" hide />
                <YAxis type="category" dataKey="model" {...AXIS} axisLine={false} width={150} />
                <Tooltip {...TOOLTIP} formatter={(v) => (typeof v === "number" ? formatCost(v) : v)} cursor={{ fill: "rgba(11,11,11,0.04)" }} />
                <Bar
                  dataKey="cost_usd"
                  name="Cost"
                  fill={C.ok}
                  maxBarSize={24}
                  radius={[0, 4, 4, 0]}
                  label={{ position: "right", fontSize: 12, fill: "#52514e", formatter: (v: unknown) => formatCost(Number(v)) }}
                />
              </BarChart>
            </ResponsiveContainer>
          )}
          {m.unpriced_models.length > 0 && (
            <p className="mt-2 text-xs text-slate-500">
              No price set for {m.unpriced_models.join(", ")}; add it to <code>MODEL_PRICES</code> on the server.
            </p>
          )}
        </Card>

        <Card title="Usage by model" subtitle="All spans with token counts">
          <table className="w-full text-left text-sm" data-testid="model-table">
            <thead className="text-xs tracking-wide text-slate-500 uppercase">
              <tr>
                <th className="py-2 font-medium">Model</th>
                <th className="py-2 text-right font-medium">Calls</th>
                <th className="py-2 text-right font-medium">Tokens in</th>
                <th className="py-2 text-right font-medium">Tokens out</th>
                <th className="py-2 text-right font-medium">Cost</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 tabular-nums">
              {m.by_model.map((u) => (
                <tr key={u.model ?? "none"}>
                  <td className="py-2 font-mono text-xs">{u.model ?? "(no model)"}</td>
                  <td className="py-2 text-right">{formatCount(u.calls)}</td>
                  <td className="py-2 text-right">{u.input_tokens.toLocaleString("en")}</td>
                  <td className="py-2 text-right">{u.output_tokens.toLocaleString("en")}</td>
                  <td className="py-2 text-right">{u.cost_usd === null ? "unpriced" : formatCost(u.cost_usd)}</td>
                </tr>
              ))}
              {m.by_model.length === 0 && (
                <tr>
                  <td colSpan={5} className="py-6 text-center text-slate-400">
                    No LLM usage in this period.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </Card>
      </div>

      <details className="mt-6 rounded-xl border border-slate-200 bg-white p-4 text-sm">
        <summary className="cursor-pointer font-medium text-slate-700">Show the time series as a table</summary>
        <table className="mt-3 w-full text-left tabular-nums" data-testid="series-table">
          <thead className="text-xs tracking-wide text-slate-500 uppercase">
            <tr>
              <th className="py-1.5 font-medium">{per === "hour" ? "Hour" : "Day"}</th>
              <th className="py-1.5 text-right font-medium">Runs</th>
              <th className="py-1.5 text-right font-medium">Failed</th>
              <th className="py-1.5 text-right font-medium">p50</th>
              <th className="py-1.5 text-right font-medium">p95</th>
              <th className="py-1.5 text-right font-medium">Cost</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {m.series.map((p) => (
              <tr key={p.start}>
                <td className="py-1.5">{bucketLabel(p.start, m.bucket)}</td>
                <td className="py-1.5 text-right">{p.runs}</td>
                <td className="py-1.5 text-right">{p.errors}</td>
                <td className="py-1.5 text-right">{formatDuration(p.p50_ms)}</td>
                <td className="py-1.5 text-right">{formatDuration(p.p95_ms)}</td>
                <td className="py-1.5 text-right">{formatCost(p.cost_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </>
  );
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3" data-testid={`tile-${label}`}>
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-slate-500">{sub}</p>}
    </div>
  );
}

function Card({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4" aria-label={title}>
      <h2 className="font-semibold">{title}</h2>
      <p className="mb-3 text-xs text-slate-500">{subtitle}</p>
      {children}
    </section>
  );
}
