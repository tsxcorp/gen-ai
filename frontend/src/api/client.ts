import type {
  Asset,
  CreateBatchRequest,
  CreateBatchResponse,
  Batch,
  EstimateRequest,
  EstimateResponse,
  PayloadResponse,
  ErrorKind,
  Manifest,
  ManifestSummary,
  Preset,
  PromptTemplate,
  ResolveRequest,
  ResolveResponse,
  ProviderId,
  ProviderInput,
  ProvidersView,
  Job,
} from "./types";
import { normalizeJob } from "../lib/job";

const TOKEN_KEY = "aigen.token";

export class ApiError extends Error {
  constructor(
    public status: number,
    public kind: ErrorKind | "unknown",
    message: string,
    public details?: unknown,
  ) {
    super(message);
  }
  get confirmRequired(): boolean {
    const d = this.details as { confirm_required?: boolean } | undefined;
    return this.kind === "confirm_required" || d?.confirm_required === true;
  }
}

// --- token -----------------------------------------------------------------
let token: string | null = null;
const listeners = new Set<() => void>();

export function initToken(): void {
  const url = new URL(window.location.href);
  const fromUrl = url.searchParams.get("token");
  if (fromUrl) {
    localStorage.setItem(TOKEN_KEY, fromUrl);
    url.searchParams.delete("token"); // do not keep the secret in the address bar / history
    window.history.replaceState(null, "", url.toString());
  }
  token = localStorage.getItem(TOKEN_KEY);
}
export function getToken(): string | null {
  return token;
}
export function setToken(t: string | null): void {
  token = t;
  if (t) localStorage.setItem(TOKEN_KEY, t);
  else {
    localStorage.removeItem(TOKEN_KEY); // the HttpOnly cookie cannot be cleared from JS; it dies with the browser session
    session = "none";
  }
  listeners.forEach((l) => l());
}

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: () => void): void {
  onUnauthorized = fn;
}

export function authHeaders(extra?: HeadersInit): Headers {
  const h = new Headers(extra);
  if (token) h.set("X-Access-Token", token);
  return h;
}

// --- session cookie (invariant 20) -------------------------------------------------
/** "none": no token known; "ok": cookie set by POST /api/session; "unsupported": backend answered 404/405; "failed": other error. */
export type SessionState = "none" | "ok" | "unsupported" | "failed";
let session: SessionState = "none";
export function getSessionState(): SessionState {
  return session;
}

/**
 * Exchange the known token (header) for an HttpOnly SameSite=Strict cookie so `<img>/<video>/<a download>`
 * need no secret in the URL. Degrades without throwing: 404/405 => "unsupported" (an older backend; assets then only
 * load if it needs no token), network error => "failed" (retried on the next call). The token is NEVER put in a URL.
 */
export async function establishSession(): Promise<SessionState> {
  if (!token) return (session = "none");
  try {
    const res = await fetch("/api/session", { method: "POST", headers: authHeaders() });
    if (res.ok) session = "ok";
    else if (res.status === 404 || res.status === 405) session = "unsupported";
    else if (res.status === 401) {
      session = "failed";
      onUnauthorized?.();
    } else session = "failed";
  } catch {
    session = "failed";
  }
  return session;
}

/** Asset URL: plain path, no secrets (the session cookie authenticates `<img>/<video>/<a>`). */
export function assetUrl(id: string): string {
  return `/api/assets/${encodeURIComponent(id)}`;
}

// --- core ------------------------------------------------------------------
async function toError(res: Response): Promise<ApiError> {
  let kind: ErrorKind | "unknown" = "unknown";
  let message = `HTTP ${res.status}`;
  let details: unknown;
  try {
    const body = (await res.json()) as { error?: { kind?: ErrorKind; message?: string; details?: unknown } };
    if (body.error) {
      kind = body.error.kind ?? "unknown";
      message = body.error.message ?? message;
      details = body.error.details;
    }
  } catch {
    /* non-JSON body */
  }
  if (res.status === 401) {
    kind = "auth";
    message = "Cần token truy cập (401)";
    onUnauthorized?.();
  }
  if ((res.status === 409 || res.status === 412) && kind === "unknown") kind = "confirm_required";
  return new ApiError(res.status, kind, message, details);
}

async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = authHeaders(init.headers);
  if (init.body && typeof init.body === "string") headers.set("Content-Type", "application/json");
  let res: Response;
  try {
    res = await fetch(path, { ...init, headers });
  } catch (e) {
    throw new ApiError(0, "network", `Không kết nối được backend: ${(e as Error).message}`);
  }
  if (!res.ok) throw await toError(res);
  return res;
}

async function json<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await request(path, init);
  return (await res.json()) as T;
}

const post = <T>(path: string, body?: unknown) =>
  json<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
const put = <T>(path: string, body: unknown) => json<T>(path, { method: "PUT", body: JSON.stringify(body) });

const del = <T>(path: string) => json<T>(path, { method: "DELETE" });

function unwrapList<T>(res: unknown, ...keys: string[]): T[] {
  if (Array.isArray(res)) return res as T[];
  const o = (res ?? {}) as Record<string, unknown>;
  for (const k of ["items", ...keys]) if (Array.isArray(o[k])) return o[k] as T[];
  return [];
}

// --- endpoints ---------------------------------------------------------------
export const api = {
  manifests: async () => unwrapList<ManifestSummary>(await json<unknown>("/api/manifests"), "manifests", "models"),
  manifest: (id: string) => json<Manifest>(`/api/manifests/${encodeURIComponent(id)}`),
  resolve: (req: ResolveRequest) => post<ResolveResponse>("/api/resolve", req),
  estimate: (req: EstimateRequest) => post<EstimateResponse>("/api/estimate", req),
  payload: (req: EstimateRequest) => post<PayloadResponse>("/api/payload", req),
  createBatch: async (req: CreateBatchRequest) => {
    const r = await post<CreateBatchResponse>("/api/batches", req);
    return { ...r, jobs: (r.jobs ?? []).map(normalizeJob) };
  },
  batch: async (id: string): Promise<Batch> => {
    const b = await json<Batch>(`/api/batches/${encodeURIComponent(id)}`);
    return { ...b, jobs: (b.jobs ?? []).map(normalizeJob) };
  },
  cancelBatch: (id: string) => post<unknown>(`/api/batches/${encodeURIComponent(id)}/cancel`),
  retryJob: async (id: string): Promise<Job> => normalizeJob(await post<unknown>(`/api/jobs/${encodeURIComponent(id)}/retry`)),
  upload: async (file: File, hasPerson: boolean, consent: boolean): Promise<Asset> => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("hasPerson", String(hasPerson));
    fd.append("consent", String(consent));
    const res = await request("/api/uploads", { method: "POST", body: fd });
    const a = (await res.json()) as Asset | { asset: Asset };
    return "asset" in a ? a.asset : a;
  },
  zip: async (assetIds: string[]): Promise<Blob> => {
    const res = await request("/api/zip", { method: "POST", body: JSON.stringify({ assetIds }) });
    return res.blob();
  },
  enhance: (modelId: string, prompt: string) => post<{ suggestion: string }>("/api/enhance", { modelId, prompt }),
  presets: async () => unwrapList<Preset>(await json<unknown>("/api/presets"), "presets"),
  upsertPreset: (p: Preset) => put<Preset>(`/api/presets/${encodeURIComponent(p.id)}`, p),
  deletePreset: (id: string) => del<unknown>(`/api/presets/${encodeURIComponent(id)}`),
  prompts: async () => unwrapList<PromptTemplate>(await json<unknown>("/api/prompts"), "prompts"),
  upsertPrompt: (p: PromptTemplate) => put<PromptTemplate>(`/api/prompts/${encodeURIComponent(p.id)}`, p),
  deletePrompt: (id: string) => del<unknown>(`/api/prompts/${encodeURIComponent(id)}`),
  providers: async (): Promise<ProvidersView> => {
    const r = await json<Record<string, unknown>>("/api/providers");
    const nested = r["providers"] as ProvidersView | undefined;
    if (nested && typeof nested === "object") return nested;
    // older backend: flat Vertex view
    if (!("vertex" in r) && !("openai" in r) && !("byteplus" in r)) return { vertex: r };
    return r as ProvidersView;
  },
  saveProvider: (id: ProviderId, input: ProviderInput) => put<unknown>(`/api/providers/${id}`, input),
  testProvider: (id: ProviderId) => post<{ ok?: boolean; message?: string }>(`/api/providers/${id}/test`),
  deleteProvider: async (id: ProviderId): Promise<void> => {
    await request(`/api/providers/${id}`, { method: "DELETE" }); // body may be empty (204)
  },
};
