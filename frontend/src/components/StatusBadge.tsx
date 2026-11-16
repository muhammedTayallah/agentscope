import type { Status } from "../lib/api";

export function StatusBadge({ status }: { status: Status }) {
  const ok = status === "ok";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${
        ok ? "bg-emerald-50 text-emerald-700 ring-emerald-200" : "bg-red-50 text-red-700 ring-red-200"
      }`}
    >
      <span className={`size-1.5 rounded-full ${ok ? "bg-emerald-500" : "bg-red-500"}`} aria-hidden />
      {status}
    </span>
  );
}

const KIND_STYLES = {
  span: "bg-slate-100 text-slate-600",
  llm: "bg-violet-100 text-violet-700",
  tool: "bg-amber-100 text-amber-800",
} as const;

export function KindBadge({ kind }: { kind: keyof typeof KIND_STYLES }) {
  return (
    <span className={`rounded px-1.5 py-0.5 font-mono text-[0.65rem] font-semibold uppercase ${KIND_STYLES[kind]}`}>
      {kind}
    </span>
  );
}
