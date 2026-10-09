import type { Constraint, ResolveError, Manifest, ParamDef, ParamValue, Params, Scalar } from "../api/types";

/**
 * Local mirror of the declarative constraint rules. The backend (POST /api/resolve)
 * is authoritative; this only gives instant feedback (hide / lock / block).
 */

export interface ResolveResult {
  /** params with defaults filled and forced values applied */
  effective: Params;
  /** key -> reason for fields locked by a force rule */
  locked: Record<string, string>;
  /** key -> allowed values when a rule restricts to more than one value */
  allowed: Record<string, Scalar[]>;
  errors: string[];
  /** same errors with the param key they belong to (matches backend `{key, reason}`) */
  errorItems: ResolveError[];
}

export function isSupported(p: ParamDef): boolean {
  return p.supported !== false;
}

export function appliesToMode(p: ParamDef, mode: string): boolean {
  return !p.appliesToModes || p.appliesToModes.length === 0 || p.appliesToModes.includes(mode);
}

/** Params that exist for this model+mode and are allowed to be shown/sent. */
export function visibleParams(m: Manifest, mode: string): ParamDef[] {
  return m.params.filter((p) => isSupported(p) && appliesToMode(p, mode));
}

export function paramRange(p: ParamDef): { min: number; max: number; step?: number } | null {
  if (!p.range) return null;
  if (Array.isArray(p.range)) return { min: p.range[0], max: p.range[1] };
  return p.range;
}

function asList(v: Scalar | Scalar[]): Scalar[] {
  return Array.isArray(v) ? v : [v];
}

function eq(a: unknown, b: unknown): boolean {
  // tolerate "8" vs 8 coming from selects
  return a === b || (a !== null && b !== null && a !== undefined && b !== undefined && String(a) === String(b));
}

export function whenMatches(c: Constraint, values: Record<string, unknown>): boolean {
  const keys = Object.keys(c.when);
  if (keys.length === 0) return false;
  return keys.every((k) => {
    const v = values[k];
    if (v === undefined || v === null) return false;
    return asList(c.when[k] as Scalar | Scalar[]).some((x) => eq(x, v));
  });
}

export function isBlockRule(c: Constraint): boolean {
  return c.block === true || (c.then !== undefined && (c.then as Record<string, unknown>)["block"] === true);
}

export function withDefaults(m: Manifest, mode: string, params: Params): Params {
  const out: Params = { ...params };
  for (const p of visibleParams(m, mode)) {
    if (out[p.key] === undefined && p.default !== undefined) out[p.key] = p.default;
  }
  return out;
}

/** Drop keys that are unsupported / not applicable in this mode (invariant 11). */
export function pruneParams(m: Manifest, mode: string, params: Params): Params {
  const keys = new Set(visibleParams(m, mode).map((p) => p.key));
  const out: Params = {};
  for (const [k, v] of Object.entries(params)) if (keys.has(k)) out[k] = v;
  return out;
}

export function resolveConstraints(m: Manifest, mode: string, params: Params): ResolveResult {
  const visible = new Set(visibleParams(m, mode).map((p) => p.key));
  const effective: Params = withDefaults(m, mode, pruneParams(m, mode, params));
  const locked: Record<string, string> = {};
  const allowed: Record<string, Scalar[]> = {};
  // Fixpoint: a forced value may trigger another rule. Bounded to avoid cycles.
  for (let pass = 0; pass < 8; pass++) {
    let changed = false;
    const ctx: Record<string, unknown> = { ...effective, mode };
    for (const c of m.constraints) {
      if (!whenMatches(c, ctx) || isBlockRule(c) || !c.then) continue;
      for (const [key, raw] of Object.entries(c.then)) {
        if (key === "block" || !visible.has(key)) continue;
        const list = asList(raw as Scalar | Scalar[]);
        if (list.length === 1) {
          const forced = list[0] as Scalar;
          locked[key] = c.reason;
          delete allowed[key];
          if (!eq(effective[key], forced)) {
            effective[key] = forced;
            changed = true;
          }
        } else if (list.length > 1) {
          allowed[key] = list;
          if (!list.some((x) => eq(x, effective[key]))) {
            effective[key] = list[0] as Scalar;
            changed = true;
          }
        }
      }
    }
    if (!changed) break;
  }

  // Invariant 22/16: block rules are evaluated ONCE, on the state AFTER the fixpoint (same as backend).
  const ctx: Record<string, unknown> = { ...effective, mode };
  const items: ResolveError[] = [];
  for (const c of m.constraints) {
    if (isBlockRule(c) && whenMatches(c, ctx)) items.push({ key: Object.keys(c.when).join(","), reason: c.reason });
  }
  items.push(...validateValueItems(m, mode, effective));
  const seen = new Set<string>();
  const errorItems = items.filter((e) => (seen.has(e.reason) ? false : (seen.add(e.reason), true)));
  return { effective, locked, allowed, errors: errorItems.map((e) => e.reason), errorItems };
}

/** Enum membership / numeric range / bool checks against the manifest. */
export function validateValues(m: Manifest, mode: string, params: Params): string[] {
  return validateValueItems(m, mode, params).map((e) => e.reason);
}

export function validateValueItems(m: Manifest, mode: string, params: Params): ResolveError[] {
  const errors: ResolveError[] = [];
  for (const p of visibleParams(m, mode)) {
    const v = params[p.key];
    if (v === undefined || v === null || v === "") continue;
    const label = p.label ?? p.key;
    if ((p.type === "enum" || p.type === "ratio") && p.values) {
      if (!p.values.some((x) => eq(x, v))) errors.push({ key: p.key, reason: `${label}: giá trị "${String(v)}" không được model hỗ trợ` });
    } else if (p.type === "int" || p.type === "float") {
      const n = Number(v);
      const r = paramRange(p);
      if (!Number.isFinite(n)) errors.push({ key: p.key, reason: `${label}: không phải số` });
      else {
        if (p.type === "int" && !Number.isInteger(n)) errors.push({ key: p.key, reason: `${label}: phải là số nguyên` });
        if (r && (n < r.min || n > r.max)) errors.push({ key: p.key, reason: `${label}: phải trong khoảng ${r.min}–${r.max}` });
      }
    } else if (p.type === "bool" && typeof v !== "boolean") {
      errors.push({ key: p.key, reason: `${label}: phải là true/false` });
    }
  }
  return errors;
}

/** Options for an enum field after applying `allowed` restrictions. */
export function enumOptions(p: ParamDef, allowed: Record<string, Scalar[]>): Scalar[] {
  const base = p.values ?? [];
  const a = allowed[p.key];
  return a ? base.filter((v) => a.some((x) => eq(x, v))) : base;
}

/**
 * Carry values over when switching models: keep keys that exist (and are valid) in the
 * target manifest, otherwise use defaults. Prompt lives outside params so it is kept.
 */
export function carryParams(from: Params, to: Manifest, mode: string): Params {
  const out: Params = {};
  for (const p of visibleParams(to, mode)) {
    const v = from[p.key];
    const ok =
      v !== undefined &&
      ((p.type !== "enum" && p.type !== "ratio") || !p.values || p.values.some((x) => eq(x, v)));
    if (ok) out[p.key] = v as ParamValue;
  }
  return out;
}

/** Pick a valid mode for a manifest, preferring `preferred`. */
export function pickMode(m: Manifest, preferred?: string): string {
  if (preferred && m.modes.includes(preferred)) return preferred;
  return m.modes[0] ?? "default";
}

/** ASSUMPTION: video modes are named t2v | i2v | first_last (requirements sketch). */
export function inferMode(m: Manifest, slots: Record<string, unknown>, current: string): string {
  if (m.kind !== "video") return current;
  const has = (k: string) => {
    const v = slots[k];
    return Array.isArray(v) ? v.length > 0 : Boolean(v);
  };
  const want = has("last_frame") ? "first_last" : has("first_frame") ? "i2v" : "t2v";
  return m.modes.includes(want) ? want : current;
}
