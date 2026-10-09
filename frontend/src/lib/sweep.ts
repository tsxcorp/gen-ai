import type { EstimateResponse, GenerationRequest, Params, Scalar, SweepAxis, SweepSpec } from "../api/types";

export const MAX_AXES = 2;

export function emptySweep(): SweepSpec {
  return { variants: 1, prompts: [], axes: [], seedMode: "none" };
}

/** Parse the multi-line prompt list: one prompt per non-empty line. */
export function parsePromptList(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean);
}

/** Axis values typed as "1K, 2K, 4K" -> typed according to the param. Prompt axes: one value per LINE (prompts contain commas). */
export function parseAxisValues(text: string, type: string, key?: string): Scalar[] {
  return text
    .split(key === "prompt" ? /\n/ : /[,\n;]/)
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s): Scalar => {
      if (type === "int" || type === "float") {
        const n = Number(s);
        return Number.isFinite(n) ? n : s;
      }
      if (type === "bool") return s === "true";
      return s;
    });
}

export function cleanAxes(axes: SweepAxis[]): SweepAxis[] {
  return axes
    .filter((a) => a.param && a.values.length > 0)
    .slice(0, MAX_AXES)
    .map((a) => ({ param: a.param, values: [...new Set(a.values)] }));
}

/** Number of jobs a sweep expands to (before the backend's native-count merging). */
export function countJobs(sweep: SweepSpec): number {
  const n = Math.max(1, Math.floor(sweep.variants) || 1);
  const prompts = Math.max(1, sweep.prompts.length);
  const axes = cleanAxes(sweep.axes).reduce((acc, a) => acc * a.values.length, 1);
  return n * prompts * axes;
}

/** Concrete param/prompt combinations of the prompt x axes grid (without N). */
export function expandCells(base: GenerationRequest, sweep: SweepSpec): { prompt: string; params: Params }[] {
  const prompts = sweep.prompts.length > 0 ? sweep.prompts : [base.prompt];
  let combos: Params[] = [{}];
  for (const axis of cleanAxes(sweep.axes)) {
    combos = combos.flatMap((c) => axis.values.map((v) => ({ ...c, [axis.param]: v })));
  }
  return prompts.flatMap((prompt) => combos.map((c) => ({ prompt, params: { ...base.params, ...c } })));
}

export function formatUsd(n: number): string {
  if (!Number.isFinite(n)) return "?";
  if (n === 0) return "$0";
  return n < 0.1 ? `$${n.toFixed(3)}` : `$${n.toFixed(2)}`;
}

export function formatRange(min: number, max: number): string {
  return Math.abs(min - max) < 1e-9 ? formatUsd(min) : `${formatUsd(min)}–${formatUsd(max)}`;
}

/** Footer label: "18 job · $0.40–$0.80" (or just jobs while the estimate is loading). */
export function footerLabel(jobCount: number, est?: Pick<EstimateResponse, "minUsd" | "maxUsd"> | null): string {
  const jobs = `${jobCount} job`;
  return est ? `${jobs} · ${formatRange(est.minUsd, est.maxUsd)}` : `${jobs} · …`;
}

/**
 * Whether the user must confirm before creating the batch. Uses the backend's
 * `confirmRequired` flag when present, else compares with `thresholdUsd` if given.
 */
export function needsConfirm(est: EstimateResponse | null | undefined): boolean {
  if (!est) return false;
  if (est.unknownPrice) return true; // invariant 15
  if (typeof est.confirmRequired === "boolean") return est.confirmRequired;
  if (typeof est.thresholdUsd === "number") return est.maxUsd > est.thresholdUsd;
  return false;
}

export function isStalePrice(lastVerified: string | null | undefined, now: Date = new Date(), days = 30): boolean {
  if (!lastVerified) return true;
  const t = Date.parse(lastVerified);
  if (Number.isNaN(t)) return true;
  return now.getTime() - t > days * 86_400_000;
}

/**
 * Local counterpart of the backend's axis warnings (invariant 22): axes the current mode does not use
 * (silently dropped by resolve) or that a force rule pins to one value (N identical paid jobs).
 * `visibleKeys` = params applicable to the current model+mode; `locked` = key -> reason from resolve.
 */
export function axisWarnings(axes: SweepAxis[], visibleKeys: Set<string>, locked: Record<string, string>): string[] {
  const out: string[] = [];
  for (const a of cleanAxes(axes)) {
    if (!visibleKeys.has(a.param)) out.push(`Trục "${a.param}" không áp dụng cho chế độ hiện tại: bị bỏ qua, các job sẽ trùng nhau.`);
    else if (locked[a.param] && a.values.length > 1)
      out.push(`Trục "${a.param}" bị luật ép về một giá trị (${locked[a.param]}): ${a.values.length} giá trị sẽ gộp thành một, các job trùng nhau.`);
  }
  return out;
}

/** Backend rejects `sweep.prompts` together with an axis on `prompt` (core/expand.py). Catch it before sending. */
export function sweepConflict(sweep: SweepSpec): string | null {
  const hasPromptAxis = cleanAxes(sweep.axes).some((a) => a.param === "prompt");
  return hasPromptAxis && sweep.prompts.length > 0 ? "Dùng danh sách prompt hoặc trục prompt, không dùng cả hai." : null;
}
