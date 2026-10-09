import { describe, expect, it } from "vitest";
import { veo } from "./fixtures";
import { buildPayloadPreview, parsePayloadEdit } from "./payload";
import { resolveConstraints } from "./constraints";
import { normalizeJob, diffKeys } from "./job";
import { parseSseBlock } from "../api/sse";

describe("raw request payload", () => {
  const eff = resolveConstraints(veo, "t2v", { resolution: "1080p", seed: 7 }).effective;
  const payload = buildPayloadPreview(veo, "t2v", "a cat", eff);

  it("builds nested payload from providerPath, only supported fields", () => {
    expect(payload).toEqual({
      instances: [{ prompt: "a cat" }],
      parameters: { aspectRatio: "16:9", resolution: "1080p", durationSeconds: 8, seed: 7 },
    });
  });

  it("round-trips through edit parsing", () => {
    const r = parsePayloadEdit(veo, "t2v", JSON.stringify(payload));
    expect(r.ok).toBe(true);
    expect(r.prompt).toBe("a cat");
    expect(r.params).toMatchObject({ resolution: "1080p", duration: 8, seed: 7 });
  });

  it("rejects invalid JSON, unknown fields, and invalid values", () => {
    expect(parsePayloadEdit(veo, "t2v", "{oops").ok).toBe(false);
    const unknown = parsePayloadEdit(veo, "t2v", JSON.stringify({ ...payload, parameters: { ...(payload["parameters"] as object), hax: 1 } }));
    expect(unknown.ok).toBe(false);
    expect(unknown.errors.join()).toMatch(/parameters\.hax/);
    const bad = parsePayloadEdit(veo, "t2v", JSON.stringify({ parameters: { resolution: "8k" } }));
    expect(bad.ok).toBe(false);
  });

  it("unknown fields are only warnings for the real backend payload", () => {
    const r = parsePayloadEdit(veo, "t2v", JSON.stringify({ ...payload, model: "x" }), false);
    expect(r.ok).toBe(true);
    expect(r.warnings.join()).toMatch(/model/);
  });

  it("applies providerFormat both ways", () => {
    const m = { ...veo, params: veo.params.map((p) => (p.key === "duration" ? { ...p, type: "int" as const, values: undefined, range: { min: 3, max: 10 }, providerFormat: "{}s" } : p)) };
    const pl = buildPayloadPreview(m, "t2v", "x", { duration: 5 });
    expect(pl).toMatchObject({ parameters: { durationSeconds: "5s" } });
    expect(parsePayloadEdit(m, "t2v", JSON.stringify(pl)).params["duration"]).toBe(5);
  });

  it("rejects the unsupported field even though it has a providerPath", () => {
    const r = parsePayloadEdit(veo, "t2v", JSON.stringify({ parameters: { legacy: "x" } }));
    expect(r.ok).toBe(false);
  });
});

describe("job helpers + sse", () => {
  it("normalizeJob accepts `model` and thin jobs", () => {
    const j = normalizeJob({ id: "1", batch_id: "b", model: "veo-3.1", status: "running" });
    expect(j).toMatchObject({ modelId: "veo-3.1", batchId: "b", assets: [], requestedParams: {} });
  });
  it("diffKeys finds differing params", () => {
    const a = normalizeJob({ id: "1", effectiveParams: { x: 1, y: 2 } });
    const b = normalizeJob({ id: "2", effectiveParams: { x: 1, y: 3 } });
    expect([...diffKeys([a, b])]).toEqual(["y"]);
  });
  it("parses SSE blocks", () => {
    expect(parseSseBlock('event: job.updated\ndata: {"id":"1"}')).toEqual({ event: "job.updated", data: { id: "1" } });
    expect(parseSseBlock(": keepalive")).toBeNull();
  });
});
