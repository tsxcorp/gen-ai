import { describe, expect, it, vi } from "vitest";
import type { Job } from "../api/types";
import { jobWarnings } from "../grid/AssetView";
import { newId } from "./id";
import { normalizeJob, unsavedFor } from "./job";
import { axisWarnings, needsConfirm, parseAxisValues, sweepConflict, emptySweep } from "./sweep";

describe("newId", () => {
  it("works when crypto.randomUUID is missing (http origin)", () => {
    vi.stubGlobal("crypto", { getRandomValues: (a: Uint8Array) => a.fill(7) });
    expect(newId()).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    vi.stubGlobal("crypto", undefined);
    expect(newId()).toMatch(/^[0-9a-f-]{36}$/);
    vi.unstubAllGlobals();
  });
});

describe("multi-asset jobs (review #5)", () => {
  const job = normalizeJob({
    id: "j", batchId: "b", modelId: "veo", status: "succeeded", variantCount: 3,
    assets: [{ id: "a1", mime: "video/mp4" }, { id: "a2", mime: "video/mp4" }, { id: "a3", mime: "video/mp4" }],
  });
  it("downloading one asset leaves the others unsaved", () => {
    expect(unsavedFor([job], { a1: true })).toEqual(["a2", "a3"]);
  });
  it("shows job warnings, or a local note when assets < variantCount", () => {
    expect(jobWarnings({ ...job, warnings: ["raiMediaFilteredCount=1"] } as Job)).toEqual(["raiMediaFilteredCount=1"]);
    expect(jobWarnings({ ...job, assets: job.assets.slice(0, 2) })[0]).toMatch(/2\/3/);
    expect(jobWarnings(job)).toEqual([]);
  });
});

describe("sweep extras", () => {
  it("prompt axis values are split by line, not by comma", () => {
    expect(parseAxisValues("a cat, in a hat\nb dog", "text", "prompt")).toEqual(["a cat, in a hat", "b dog"]);
  });
  it("warns for ignored and force-collapsed axes", () => {
    const w = axisWarnings([{ param: "x", values: [1, 2] }, { param: "duration", values: [4, 6] }], new Set(["duration"]), { duration: "ép 8s" });
    expect(w).toHaveLength(2);
  });
  it("flags prompt list + prompt axis together (backend rejects it)", () => {
    const axes = [{ param: "prompt", values: ["a", "b"] }];
    expect(sweepConflict({ ...emptySweep(), axes, prompts: ["x"] })).not.toBeNull();
    expect(sweepConflict({ ...emptySweep(), axes })).toBeNull();
  });
  it("unknown price always needs confirmation", () => {
    expect(needsConfirm({ jobCount: 1, minUsd: 0, maxUsd: 0, unknownPrice: true, confirmRequired: false })).toBe(true);
  });
});
