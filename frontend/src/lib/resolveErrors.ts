import type { ResolveError } from "../api/types";

/**
 * `/api/resolve` returns `errors: [{key, reason}]`. Older shapes (plain strings) and
 * malformed entries are tolerated: whatever arrives, the result is always `{key, reason}`
 * with string fields, so rendering can never throw "Objects are not valid as a React child".
 */
export function normalizeServerErrors(raw: unknown): ResolveError[] {
  if (!Array.isArray(raw)) return [];
  const out: ResolveError[] = [];
  for (const e of raw) {
    if (typeof e === "string") out.push({ key: "", reason: e });
    else if (e && typeof e === "object") {
      const o = e as Record<string, unknown>;
      const reason = typeof o["reason"] === "string" ? o["reason"] : typeof o["message"] === "string" ? o["message"] : JSON.stringify(e);
      out.push({ key: typeof o["key"] === "string" ? o["key"] : "", reason });
    } else if (e !== null && e !== undefined) out.push({ key: "", reason: String(e) });
  }
  return out;
}

/**
 * Merge local-engine errors with the server's. One error per key (the local message wins
 * since it is localized); keyless entries are deduped by text.
 */
export function mergeResolveErrors(local: ResolveError[], server: ResolveError[]): ResolveError[] {
  const out = [...local];
  const keys = new Set(local.map((e) => e.key).filter(Boolean));
  const reasons = new Set(local.map((e) => e.reason));
  for (const e of server) {
    if (reasons.has(e.reason) || (e.key && keys.has(e.key))) continue;
    out.push(e);
    reasons.add(e.reason);
    if (e.key) keys.add(e.key);
  }
  return out;
}
