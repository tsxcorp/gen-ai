import { describe, expect, it } from "vitest";
import type { ManifestSummary } from "../api/types";
import {
  buildBytePlusPayload,
  buildOpenAIPayload,
  buildVertexPayload,
  groupModels,
  jobProvider,
  notConfiguredMessage,
  providersWithModels,
  type VertexForm,
} from "./providers";

const m = (id: string, kind: "image" | "video", provider?: ManifestSummary["provider"], configured?: boolean): ManifestSummary => ({
  id,
  kind,
  status: "ga",
  provider,
  configured,
});
const models = [
  m("nb", "image", "vertex", true),
  m("veo", "video", "vertex", true),
  m("gpt", "image", "openai", false),
  m("seed", "video", "byteplus", true),
  m("legacy", "image"), // older backend: no provider field
];

describe("provider grouping/filtering", () => {
  it("groups by provider (registry order) then kind (image first); missing provider => vertex", () => {
    const g = groupModels(models);
    expect(g.map((x) => x.provider)).toEqual(["vertex", "openai", "byteplus"]);
    expect(g[0]!.kinds.map((k) => [k.kind, k.models.map((x) => x.id)])).toEqual([
      ["image", ["nb", "legacy"]],
      ["video", ["veo"]],
    ]);
    expect(g[1]!.kinds).toHaveLength(1);
  });
  it("flags unconfigured providers, treats absent `configured` as configured", () => {
    const g = groupModels(models);
    expect(g.map((x) => x.configured)).toEqual([true, false, true]);
  });
  it("filters by provider", () => {
    expect(groupModels(models, "openai").map((x) => x.provider)).toEqual(["openai"]);
    expect(groupModels(models, "byteplus")[0]!.kinds[0]!.models[0]!.id).toBe("seed");
    expect(groupModels([m("a", "image", "vertex")], "openai")).toEqual([]);
  });
  it("lists chips only for providers that have models", () => {
    expect(providersWithModels(models.filter((x) => x.provider !== "openai"))).toEqual(["vertex", "byteplus"]);
  });
  it("explains why Generate is disabled", () => {
    expect(notConfiguredMessage(models[2])).toMatch(/OpenAI/);
    expect(notConfiguredMessage(models[0])).toBeNull();
    expect(notConfiguredMessage(undefined)).toBeNull();
  });
  it("resolves a job's provider from the job or the manifest", () => {
    expect(jobProvider({ modelId: "seed" }, models)).toBe("byteplus");
    expect(jobProvider({ modelId: "seed", provider: "openai" }, models)).toBe("openai");
    expect(jobProvider({ modelId: "unknown" }, models)).toBeNull();
  });
});

describe("settings payloads match PUT /api/providers/{id}", () => {
  const base: VertexForm = { authMethod: "service_account", projectId: " p1 ", location: "global", gcsBucket: "", source: "json", path: "/x.json", json: "" };
  it("vertex service_account: blank key keeps stored key (no key fields)", () => {
    expect(buildVertexPayload(base)).toEqual({ authMethod: "service_account", projectId: "p1", location: "global" });
  });
  it("vertex service_account: only the active source is sent", () => {
    expect(buildVertexPayload({ ...base, json: '{"a":1}' })).toEqual({ authMethod: "service_account", projectId: "p1", location: "global", json: '{"a":1}' });
    expect(buildVertexPayload({ ...base, source: "path", json: '{"a":1}' })).toEqual({
      authMethod: "service_account", projectId: "p1", location: "global", serviceAccountPath: "/x.json",
    });
    expect(buildVertexPayload({ ...base, source: "file", gcsBucket: "b" })).toEqual({ authMethod: "service_account", projectId: "p1", location: "global", gcsBucket: "b" });
  });
  it("vertex adc: never sends key material even if inputs still hold text", () => {
    const p = buildVertexPayload({ ...base, authMethod: "adc", json: "{}", path: "/x.json", source: "path" });
    expect(p).toEqual({ authMethod: "adc", projectId: "p1", location: "global" });
  });
  it("openai: omits empty apiKey/organization/project", () => {
    expect(buildOpenAIPayload({ apiKey: "  ", organization: "", project: "" })).toEqual({});
    expect(buildOpenAIPayload({ apiKey: " sk-1 ", organization: "org", project: "" })).toEqual({ apiKey: "sk-1", organization: "org" });
  });
  it("byteplus: omits empty apiKey/region", () => {
    expect(buildBytePlusPayload({ apiKey: "", region: "" })).toEqual({});
    expect(buildBytePlusPayload({ apiKey: "k", region: "ap-southeast" })).toEqual({ apiKey: "k", region: "ap-southeast" });
  });
});
