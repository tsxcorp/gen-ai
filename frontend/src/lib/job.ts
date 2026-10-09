import type { Job, JobStatus } from "../api/types";

/** Tolerate `model` vs `modelId`, missing arrays, etc. so the UI never crashes on a thin job. */
export function normalizeJob(raw: unknown): Job {
  const j = (raw ?? {}) as Record<string, unknown>;
  const status = (j["status"] as JobStatus) ?? "queued";
  return {
    ...(j as unknown as Job),
    id: String(j["id"]),
    batchId: String(j["batchId"] ?? j["batch_id"] ?? ""),
    modelId: String(j["modelId"] ?? j["model"] ?? ""),
    requestedParams: (j["requestedParams"] as Job["requestedParams"]) ?? {},
    effectiveParams: (j["effectiveParams"] as Job["effectiveParams"]) ?? (j["requestedParams"] as Job["requestedParams"]) ?? {},
    status,
    assets: Array.isArray(j["assets"]) ? (j["assets"] as Job["assets"]) : [],
    warnings: Array.isArray(j["warnings"]) ? (j["warnings"] as unknown[]).map(String) : undefined,
  };
}

export function jobPrompt(j: Job): string {
  if (j.prompt) return j.prompt;
  const p = j.requestedParams["prompt"];
  return typeof p === "string" ? p : "";
}

export function isActive(s: JobStatus): boolean {
  return s === "queued" || s === "running";
}

/** Keys whose value differs between jobs (for the compare view). */
export function diffKeys(jobs: Job[]): Set<string> {
  const keys = new Set<string>();
  const all = new Set(jobs.flatMap((j) => Object.keys(j.effectiveParams)));
  for (const k of all) {
    const vals = new Set(jobs.map((j) => JSON.stringify(j.effectiveParams[k] ?? null)));
    if (vals.size > 1) keys.add(k);
  }
  return keys;
}

/** Asset ids of succeeded jobs not yet downloaded: tracked PER ASSET (a Veo group has several). */
export function unsavedFor(jobs: Job[], downloaded: Record<string, true>): string[] {
  return jobs.filter((j) => j.status === "succeeded").flatMap((j) => j.assets.map((a) => a.id)).filter((id) => !downloaded[id]);
}
