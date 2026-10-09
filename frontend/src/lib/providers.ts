import type {
  BytePlusProviderInput,
  Job,
  ManifestSummary,
  ModelKind,
  OpenAIProviderInput,
  ProviderId,
  VertexAuthMethod,
  VertexProviderInput,
} from "../api/types";

export const PROVIDER_IDS: ProviderId[] = ["vertex", "openai", "byteplus"];
export const PROVIDER_LABEL: Record<ProviderId, string> = {
  vertex: "Vertex",
  openai: "OpenAI",
  byteplus: "BytePlus",
};
export const PROVIDER_TITLE: Record<ProviderId, string> = {
  vertex: "Vertex AI (Google)",
  openai: "OpenAI",
  byteplus: "BytePlus (Seedance)",
};

export type ProviderFilter = "all" | ProviderId;
export const KIND_LABEL: Record<ModelKind, string> = { image: "Ảnh", video: "Video" };

export function providerOf(m: Pick<ManifestSummary, "provider">): ProviderId {
  return m.provider && PROVIDER_IDS.includes(m.provider) ? m.provider : "vertex";
}
/** Absent `configured` (older backend) counts as configured: never block on a missing field. */
export function isConfigured(m: Pick<ManifestSummary, "configured">): boolean {
  return m.configured !== false;
}

export interface ModelGroup {
  provider: ProviderId;
  configured: boolean;
  kinds: { kind: ModelKind; models: ManifestSummary[] }[];
}

/** Group models by provider then kind (image before video), applying the provider filter. Empty groups are dropped. */
export function groupModels(models: ManifestSummary[], filter: ProviderFilter = "all"): ModelGroup[] {
  const out: ModelGroup[] = [];
  for (const provider of PROVIDER_IDS) {
    if (filter !== "all" && filter !== provider) continue;
    const mine = models.filter((m) => providerOf(m) === provider);
    if (!mine.length) continue;
    const kinds = (["image", "video"] as ModelKind[])
      .map((kind) => ({ kind, models: mine.filter((m) => m.kind === kind) }))
      .filter((k) => k.models.length > 0);
    out.push({ provider, configured: mine.every(isConfigured), kinds });
  }
  return out;
}

/** Providers that actually have models (for the filter chips), in registry order. */
export function providersWithModels(models: ManifestSummary[]): ProviderId[] {
  return PROVIDER_IDS.filter((p) => models.some((m) => providerOf(m) === p));
}

/** Why Generate is disabled for this model, or null. */
export function notConfiguredMessage(m: Pick<ManifestSummary, "provider" | "configured"> | undefined): string | null {
  if (!m || isConfigured(m)) return null;
  const p = providerOf(m);
  return `Chưa cấu hình ${PROVIDER_LABEL[p]}: vào Cài đặt để nhập thông tin xác thực trước khi Generate.`;
}

/** Provider/model for a job: job.provider if the backend sends it, else from the manifest list. */
export function jobProvider(job: Pick<Job, "modelId" | "provider">, models: ManifestSummary[]): ProviderId | null {
  if (job.provider && PROVIDER_IDS.includes(job.provider)) return job.provider;
  const m = models.find((x) => x.id === job.modelId);
  return m ? providerOf(m) : null;
}
export function jobModelLabel(job: Pick<Job, "modelId">, models: ManifestSummary[]): string {
  return models.find((x) => x.id === job.modelId)?.label ?? job.modelId;
}

// --- settings payloads (PUT /api/providers/{id}) ---------------------------------------
// Rule: a key field is only present when the user typed a new value. Blank = keep the stored key.

export interface VertexForm {
  authMethod: VertexAuthMethod;
  projectId: string;
  location: string;
  gcsBucket: string;
  /** which key input is active for service_account */
  source: "file" | "path" | "json";
  path: string;
  json: string;
}

export function buildVertexPayload(f: VertexForm): VertexProviderInput {
  const out: VertexProviderInput = { authMethod: f.authMethod, projectId: f.projectId.trim(), location: f.location.trim() };
  if (f.gcsBucket.trim()) out.gcsBucket = f.gcsBucket.trim();
  if (f.authMethod === "service_account") {
    if (f.source === "path") {
      if (f.path.trim()) out.serviceAccountPath = f.path.trim();
    } else if (f.json.trim()) out.json = f.json.trim();
  }
  return out;
}

export function buildOpenAIPayload(f: { apiKey: string; organization: string; project: string }): OpenAIProviderInput {
  const out: OpenAIProviderInput = {};
  if (f.apiKey.trim()) out.apiKey = f.apiKey.trim();
  if (f.organization.trim()) out.organization = f.organization.trim();
  if (f.project.trim()) out.project = f.project.trim();
  return out;
}

export function buildBytePlusPayload(f: { apiKey: string; region: string }): BytePlusProviderInput {
  const out: BytePlusProviderInput = {};
  if (f.apiKey.trim()) out.apiKey = f.apiKey.trim();
  if (f.region.trim()) out.region = f.region.trim();
  return out;
}
