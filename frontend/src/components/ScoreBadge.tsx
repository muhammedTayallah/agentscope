import { PASS_SCORE, formatScore } from "../lib/evals";

/** Score with a status dot and a pass/partial/fail word, so meaning never rides on colour alone. */
export function ScoreBadge({ score, title }: { score: number | null | undefined; title?: string }) {
  if (score === null || score === undefined) {
    return (
      <span className="text-slate-400" title={title}>
        —
      </span>
    );
  }
  const [dot, word] = score >= PASS_SCORE ? ["#0ca30c", "pass"] : score >= 0.5 ? ["#fab219", "partial"] : ["#d03b3b", "fail"];
  return (
    <span className="inline-flex items-center gap-1.5 tabular-nums" title={title}>
      <span className="size-2 rounded-full" style={{ background: dot }} aria-hidden />
      <span className="font-medium text-slate-800">{formatScore(score)}</span>
      <span className="text-xs text-slate-500">{word}</span>
    </span>
  );
}

export function Delta({ value }: { value: number | null }) {
  if (value === null) return <span className="text-slate-400">—</span>;
  const pts = Math.round(value * 100);
  if (pts === 0) return <span className="text-slate-500">±0</span>;
  return (
    <span className={`font-medium tabular-nums ${pts > 0 ? "text-[#006300]" : "text-red-700"}`}>
      {pts > 0 ? "▲ +" : "▼ "}
      {pts} pts
    </span>
  );
}
