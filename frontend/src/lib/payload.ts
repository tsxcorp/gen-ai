import type { Manifest, ParamDef, Params, ParamValue } from "../api/types";
import { validateValues, visibleParams } from "./constraints";

/**
 * Raw-request helpers. The authoritative payload is built by the backend adapter and
 * served by POST /api/payload; `buildPayloadPreview` is only the offline/fallback preview
 * made from manifest `providerPath`s.
 */

type Obj = Record<string, unknown>;

const isIndex = (k: string | undefined) => k !== undefined && /^\d+$/.test(k);

export function setPath(root: Obj, path: string, value: unknown): void {
  const parts = path.split(".");
  let cur: Obj | unknown[] = root;
  parts.slice(0, -1).forEach((k, i) => {
    const c = cur as Obj;
    const next = c[k];
    if (typeof next !== "object" || next === null) c[k] = isIndex(parts[i + 1]) ? [] : {};
    cur = c[k] as Obj;
  });
  (cur as Obj)[parts[parts.length - 1] as string] = value;
}

export function getPath(root: unknown, path: string): unknown {
  let cur: unknown = root;
  for (const k of path.split(".")) {
    if (typeof cur !== "object" || cur === null) return undefined;
    cur = (cur as Obj)[k];
  }
  return cur;
}

/** providerFormat "{}s": 5 -> "5s". */
export function formatForProvider(p: ParamDef, v: ParamValue): ParamValue {
  return p.providerFormat && (typeof v === "number" || typeof v === "string") ? p.providerFormat.replace("{}", String(v)) : v;
}

export function parseFromProvider(p: ParamDef, v: unknown): ParamValue {
  if (p.providerFormat && typeof v === "string") {
    const [pre = "", post = ""] = p.providerFormat.split("{}");
    if (v.startsWith(pre) && v.endsWith(post)) {
      const inner = v.slice(pre.length, v.length - post.length);
      const n = Number(inner);
      return inner !== "" && Number.isFinite(n) ? n : inner;
    }
  }
  return v as ParamValue;
}

function promptDef(m: Manifest): ParamDef | undefined {
  return m.params.find((p) => p.key === "prompt");
}

export function buildPayloadPreview(m: Manifest, mode: string, prompt: string, effective: Params): Obj {
  const root: Obj = {};
  setPath(root, promptDef(m)?.providerPath ?? "prompt", prompt);
  for (const p of visibleParams(m, mode)) {
    if (p.type === "image" || p.type === "imageList" || p.key === "prompt") continue; // assets: not inline JSON
    const v = effective[p.key];
    if (v === undefined || v === null || v === "" || !p.providerPath) continue;
    setPath(root, p.providerPath, formatForProvider(p, v));
  }
  return root;
}

export interface ParsedPayload {
  ok: boolean;
  prompt?: string;
  params: Params;
  errors: string[];
  warnings: string[];
}

function collectLeafPaths(o: unknown, prefix = "", out: string[] = []): string[] {
  if (typeof o === "object" && o !== null) {
    const entries = Object.entries(o as Obj);
    if (entries.length === 0 && prefix) out.push(prefix);
    for (const [k, v] of entries) collectLeafPaths(v, prefix ? `${prefix}.${k}` : k, out);
  } else out.push(prefix);
  return out;
}

/**
 * Validate edited raw JSON and map it back into params using providerPath.
 * `strictUnknown`: fields outside the manifest are errors (preview mode). For the real
 * backend payload they are warnings (it legitimately contains image parts, model ids, ...)
 * and are ignored when applying.
 */
export function parsePayloadEdit(m: Manifest, mode: string, text: string, strictUnknown = true): ParsedPayload {
  const res: ParsedPayload = { ok: false, params: {}, errors: [], warnings: [] };
  let json: unknown;
  try {
    json = JSON.parse(text);
  } catch (e) {
    res.errors.push(`JSON không hợp lệ: ${(e as Error).message}`);
    return res;
  }
  if (typeof json !== "object" || json === null || Array.isArray(json)) {
    res.errors.push("Payload phải là một object JSON");
    return res;
  }
  const claimed = new Set<string>();
  const promptPath = promptDef(m)?.providerPath ?? "prompt";
  const pv = getPath(json, promptPath);
  claimed.add(promptPath);
  if (typeof pv === "string") res.prompt = pv;
  else if (pv !== undefined) res.errors.push(`${promptPath}: prompt phải là chuỗi`);

  for (const p of visibleParams(m, mode)) {
    if (!p.providerPath || p.key === "prompt" || p.type === "image" || p.type === "imageList") continue;
    claimed.add(p.providerPath);
    const v = getPath(json, p.providerPath);
    if (v !== undefined) res.params[p.key] = parseFromProvider(p, v);
  }
  const claimedList = [...claimed];
  for (const leaf of collectLeafPaths(json)) {
    const known = claimedList.some((c) => leaf === c || leaf.startsWith(`${c}.`) || c.startsWith(`${leaf}.`));
    if (!known) (strictUnknown ? res.errors : res.warnings).push(`Trường "${leaf}" không có trong manifest${strictUnknown ? " (bị từ chối)" : " (bỏ qua khi áp dụng)"}`);
  }
  res.errors.push(...validateValues(m, mode, res.params));
  res.ok = res.errors.length === 0;
  return res;
}
