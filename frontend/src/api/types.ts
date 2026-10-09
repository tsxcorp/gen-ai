/**
 * API types for the frontend. Source of truth: docs/architecture.md "Contracts (API)".
 *
 * The contract table leaves several shapes open. Every ASSUMPTION below is marked
 * "ASSUMPTION" and is also listed in the implementer report. Backend: if you amend
 * architecture.md, update this file in the same change.
 *
 * AUTH (invariant 20): the access token is read from URL `?token=` once (then persisted in
 * localStorage key `aigen.token`, and removed from the address bar) and sent as header
 * `X-Access-Token` on API calls (fetch-based SSE too). On startup, if a token is known, the
 * client calls `POST /api/session` (header) and the backend sets an HttpOnly SameSite=Strict
 * cookie; `<img>/<video>/<a download>` then use plain `/api/assets/{id}` URLs. The token is never
 * placed in a URL (if `/api/session` answers 404/405 the client degrades silently). A 401 response opens a "nhập token" dialog.
 *
 * ERRORS: `{error:{kind,message,details?}}`. Besides the 7 kinds in the spec, the UI
 * treats `kind === "confirm_required"` (or `details.confirm_required === true`, or HTTP
 * 409/412 on POST /api/batches) as "ask user to confirm the cost, then resend with
 * confirmOverThreshold=true".
 */

export type ErrorKind =
  | "quota"
  | "blocked"
  | "invalid"
  | "network"
  | "timeout"
  | "auth"
  | "not_found"
  | "confirm_required"
  | "not_configured";

export interface ApiErrorBody {
  error: { kind: ErrorKind; message: string; details?: unknown };
}

export type Scalar = string | number | boolean;
export type ParamValue = Scalar | Scalar[] | null;
export type Params = Record<string, ParamValue>;

export type ProviderId = "vertex" | "openai" | "byteplus";

export type ModelStatus = "ga" | "preview" | "deprecated";
export type ModelKind = "image" | "video";

export interface ManifestSummary {
  id: string;
  kind: ModelKind;
  status: ModelStatus;
  sunsetDate?: string | null;
  lastVerified?: string | null;
  /** optional display name; UI falls back to id */
  label?: string;
  /** provider id (architecture "đa provider"); absent on an older backend => treated as vertex. */
  provider?: ProviderId;
  /** false => provider has no credentials yet (Generate disabled, batch would 400 not_configured). Absent => assume configured. */
  configured?: boolean;
  /** backend-computed warnings (stale/deprecated/sunset/preview); UI also computes its own. */
  warnings?: string[];
}

export type ParamType = "enum" | "int" | "float" | "bool" | "text" | "ratio" | "image" | "imageList";
export type ParamGroup = "size" | "style" | "reference" | "audio" | "safety" | "output" | "cost" | string;

export interface ParamDef {
  key: string;
  label?: string;
  type: ParamType;
  /** enum / ratio options */
  values?: Scalar[];
  /** int / float. ASSUMPTION: `range: {min,max,step?}` (also accepts `[min,max]`). */
  range?: { min: number; max: number; step?: number } | [number, number];
  default?: ParamValue;
  group?: ParamGroup;
  level?: "basic" | "advanced";
  /** if absent, applies to every mode */
  appliesToModes?: string[];
  providerPath?: string;
  /** e.g. "{}s": 5 is sent as "5s" */
  providerFormat?: string;
  /** false => never rendered, never sent (invariant 11). Default true. */
  supported?: boolean;
  /** backend: asset slot is required in the modes where it applies. */
  required?: boolean;
  /** max files for imageList slots. */
  maxItems?: number;
  description?: string;
  /** ASSUMPTION: optional human labels for enum values, keyed by String(value). */
  valueLabels?: Record<string, string>;
  suggestions?: string[];
  sizeRule?: {
    allow?: string[];
    multipleOf?: number;
    maxEdge?: number;
    maxRatio?: number;
    minPixels?: number;
    maxPixels?: number;
  };
}

/**
 * Constraint `when` is `{param: allowedValues[] | value}`; all keys must match.
 * The pseudo key `mode` may be used. `then` is `{param: value}` (force) or
 * `{param: value[]}` (restrict to the listed values; a single entry == force).
 * `block: true` (top level, or `then.block`) means the combination is forbidden.
 * `reason` is shown in the tooltip (ASSUMPTION: `reason` is a Vietnamese/English string).
 */
export interface Constraint {
  when: Record<string, Scalar | Scalar[]>;
  then?: Record<string, Scalar | Scalar[] | boolean>;
  block?: boolean;
  reason: string;
  /** informational; derived if absent */
  type?: "force" | "forbid";
}

export interface PricingRow {
  when?: Record<string, Scalar | Scalar[]>;
  usd: number;
}
/** Backend (schemas.py): `{unit: per_image|per_second, priceKey}`; prices live in prices.json. */
export interface Pricing {
  unit?: string;
  priceKey?: string;
  table?: PricingRow[];
  lastVerified?: string | null;
  [k: string]: unknown;
}

export interface Limits {
  maxConcurrent?: number;
  maxVariantsNative?: number;
  maxJobsPerBatch?: number;
  [k: string]: unknown;
}

export interface Manifest extends ManifestSummary {
  modes: string[];
  params: ParamDef[];
  constraints: Constraint[];
  pricing?: Pricing;
  limits?: Limits;
}

export type AssetKind = "upload" | "output";
export interface Asset {
  id: string;
  mime: string;
  sizeBytes?: number;
  sha256?: string;
  kind?: AssetKind;
  path?: string;
  width?: number;
  height?: number;
  name?: string;
}

/** Slot -> asset id (single) or ids (imageList). ASSUMPTION for `request.assets`. */
export type AssetSlots = Record<string, string | string[]>;

export interface GenerationRequest {
  modelId: string;
  mode: string;
  params: Params;
  prompt: string;
  assets: AssetSlots;
}

export type SeedMode = "random" | "fixed" | "none";
export interface SweepAxis {
  param: string;
  values: Scalar[];
}
export interface SweepSpec {
  variants: number;
  prompts: string[];
  axes: SweepAxis[];
  seedMode: SeedMode;
}

export interface ResolveRequest {
  modelId: string;
  mode: string;
  params: Params;
}
export interface ResolveError {
  key: string;
  reason: string;
}
export interface ResolveResponse {
  effectiveParams: Params;
  locked: { key: string; reason: string }[];
  /** Backend (core/constraints.py): `{key, reason}[]`. Never render these objects directly. */
  errors: ResolveError[];
  /**
   * ASSUMPTION (optional): exact provider payload for the "Request thô" tab. If the
   * backend returns it (via build_payload) the UI shows it; otherwise the UI builds a
   * preview from manifest `providerPath`s (clearly labelled as a preview).
   */
  payload?: unknown;
}

/** POST /api/payload {request, sweep} -> exact build_payload output per job (backend api/estimate.py). */
export interface PayloadResponse {
  payloads: { jobId: string; variantCount?: number; axis?: Record<string, unknown>; payload: unknown }[];
}

export interface EstimateRequest {
  request: GenerationRequest;
  sweep: SweepSpec;
}
export interface EstimateResponse {
  jobCount: number;
  /** outputs (Veo native sampleCount groups make this > jobCount) */
  outputCount?: number;
  maxJobsPerBatch?: number;
  minUsd: number;
  maxUsd: number;
  perJob?: { minUsd?: number; maxUsd?: number; [k: string]: unknown }[];
  /** collapsed/ignored axes, stale prices, unknown prices... always shown to the user. */
  warnings?: string[];
  /** invariant 15: some job has an unknown price => estimate is not a bound, confirmation required. */
  unknownPrice?: boolean;
  requestCount?: number;
  /** ASSUMPTION (optional): backend may tell us it will require confirmation. */
  confirmRequired?: boolean;
  thresholdUsd?: number;
}

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "blocked" | "canceled";
export const TERMINAL_STATUSES: JobStatus[] = ["succeeded", "failed", "blocked", "canceled"];

export interface JobError {
  kind: ErrorKind;
  message: string;
}

/**
 * Job as sent by the backend. ASSUMPTIONS: id of the model is `modelId` (requirements
 * sketch says `model`; both accepted by `normalizeJob`); `prompt`, `mode`, `progress`
 * (0..1) and `assetsIn` are optional extras; `assets` lists output assets.
 */
export interface Job {
  id: string;
  batchId: string;
  modelId: string;
  mode?: string;
  prompt?: string;
  requestedParams: Params;
  effectiveParams: Params;
  /** backend field `assetsIn`: input slot -> asset id(s) (used by Reuse). */
  assetsIn?: AssetSlots;
  locked?: { key: string; reason: string }[];
  note?: string | null;
  /** invariant 16: e.g. fewer assets than variantCount (raiMediaFilteredCount). */
  warnings?: string[];
  variantCount?: number;
  status: JobStatus;
  progress?: number;
  error?: JobError | null;
  assets: Asset[];
  costEstimateUsd?: [number, number];
  attempts?: number;
  /** optional; the UI derives it from the model manifest when absent. */
  provider?: ProviderId;
  /** ASSUMPTION: true when the backend could not cancel an in-flight job. */
  bestEffortCancel?: boolean;
}

export interface Batch {
  id: string;
  createdAt?: string;
  jobs: Job[];
  estimate?: { minUsd: number; maxUsd: number };
  confirmed?: boolean;
  status?: string;
}

export interface CreateBatchRequest {
  request: GenerationRequest;
  sweep: SweepSpec;
  confirmOverThreshold: boolean;
}
export interface CreateBatchResponse {
  batchId: string;
  jobs: Job[];
}

export interface Preset {
  id: string;
  name: string;
  modelId: string;
  mode: string;
  params: Params;
  prompt?: string;
  createdAt?: string;
}
export interface PromptTemplate {
  id: string;
  name: string;
  text: string;
  tags?: string[];
}

/**
 * presets/prompts (invariant 24): `GET` returns `{items:[…]}`; writes are per item
 * (`PUT /api/{presets|prompts}/{id}` upsert, `DELETE` .../{id}). The full-list PUT is never used.
 */

/** GET /api/providers (architecture "đa provider"). Keys are never returned, only `hasKey`. */
export type VertexAuthMethod = "service_account" | "adc";
export interface VertexProviderView {
  configured?: boolean;
  hasKey?: boolean;
  authMethod?: VertexAuthMethod | null;
  projectId?: string;
  location?: string;
  gcsBucket?: string | null;
  /** path is not secret; JSON content never returned. */
  serviceAccountPath?: string | null;
}
export interface OpenAIProviderView {
  configured?: boolean;
  hasKey?: boolean;
  organization?: string | null;
  project?: string | null;
}
export interface BytePlusProviderView {
  configured?: boolean;
  hasKey?: boolean;
  region?: string | null;
}
export interface ProvidersView {
  vertex?: VertexProviderView;
  openai?: OpenAIProviderView;
  byteplus?: BytePlusProviderView;
}

/** PUT /api/providers/{id} bodies. Key fields are OMITTED (never empty) when the user keeps the stored key. */
export interface VertexProviderInput {
  authMethod: VertexAuthMethod;
  projectId: string;
  location: string;
  gcsBucket?: string;
  /** service_account only; at most one of the two (backend keys: `serviceAccountPath` / `json`). */
  serviceAccountPath?: string;
  json?: string;
}
export interface OpenAIProviderInput {
  apiKey?: string;
  organization?: string;
  project?: string;
}
export interface BytePlusProviderInput {
  apiKey?: string;
  region?: string;
}
export type ProviderInput = VertexProviderInput | OpenAIProviderInput | BytePlusProviderInput;

export interface SseEvent {
  event: string;
  data: unknown;
}
