import { useEffect, useState } from "react";

import { type Health, fetchHealth } from "./health";

const tone = (ok: boolean) => (ok ? "bg-emerald-100 text-emerald-800" : "bg-red-100 text-red-800");

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    const load = () =>
      fetchHealth()
        .then((h) => (setHealth(h), setError(false)))
        .catch(() => setError(true));
    load();
    const id = setInterval(load, 10_000);
    return () => clearInterval(id);
  }, []);

  const rows: [string, string, boolean][] = health
    ? [
        ["Backend", health.status, health.status === "healthy"],
        ["Database", health.database, health.database === "ok"],
        ["Redis", health.redis, health.redis === "ok"],
      ]
    : [];

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 p-6">
      <div className="w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
        <h1 className="text-2xl font-semibold text-slate-900">AgentScope</h1>
        <p className="mt-1 text-sm text-slate-500">System status</p>
        {error && <p className="mt-6 rounded-lg bg-red-100 px-3 py-2 text-sm text-red-800">backend unreachable</p>}
        {!health && !error && <p className="mt-6 text-sm text-slate-500">checking…</p>}
        <dl className="mt-6 space-y-3">
          {rows.map(([label, value, ok]) => (
            <div key={label} className="flex items-center justify-between">
              <dt className="text-slate-700">{label}</dt>
              <dd data-testid={`status-${label.toLowerCase()}`} className={`rounded-full px-3 py-1 text-sm font-medium ${tone(ok)}`}>
                {value}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </main>
  );
}
