import { describe, expect, it } from "vitest";
import { carryParams, enumOptions, inferMode, resolveConstraints, validateValues, visibleParams, whenMatches } from "./constraints";
import type { Manifest } from "../api/types";
import { veo, lite } from "./fixtures";

describe("constraint engine", () => {
  it("fills defaults and hides unsupported / out-of-mode params", () => {
    const keys = visibleParams(veo, "t2v").map((p) => p.key);
    expect(keys).not.toContain("legacy");
    expect(keys).not.toContain("first_frame");
    expect(visibleParams(veo, "first_last").map((p) => p.key)).toEqual(expect.arrayContaining(["first_frame", "last_frame"]));
    expect(resolveConstraints(veo, "t2v", {}).effective).toMatchObject({ resolution: "720p", duration: 8 });
  });

  it("story 1: 1080p forces duration=8 and locks it with a reason", () => {
    const r = resolveConstraints(veo, "t2v", { resolution: "1080p", duration: 4 });
    expect(r.effective["duration"]).toBe(8);
    expect(r.locked["duration"]).toMatch(/8s/);
    expect(r.errors).toEqual([]);
  });

  it("does not lock when the rule does not match", () => {
    const r = resolveConstraints(veo, "t2v", { resolution: "720p", duration: 4 });
    expect(r.effective["duration"]).toBe(4);
    expect(r.locked).toEqual({});
  });

  it("drops params that are unsupported or not in the mode (invariant 11)", () => {
    const r = resolveConstraints(veo, "t2v", { legacy: "x", first_frame: "a", seed: 1 });
    expect(r.effective).not.toHaveProperty("legacy");
    expect(r.effective).not.toHaveProperty("first_frame");
    expect(r.effective["seed"]).toBe(1);
  });

  it("forbid rules produce errors instead of values", () => {
    const r = resolveConstraints(veo, "t2v", { resolution: "4k", aspect_ratio: "9:16" });
    expect(r.errors).toContain("4k không hỗ trợ 9:16 (fixture)");
  });

  it("tolerates string/number mismatch from <select> (\"8\" vs 8)", () => {
    expect(whenMatches({ when: { duration: [8] }, reason: "" }, { duration: "8" })).toBe(true);
  });

  it("validates enum membership and numeric ranges", () => {
    expect(validateValues(veo, "t2v", { resolution: "8k" })[0]).toMatch(/8k/);
    expect(validateValues(veo, "t2v", { seed: -1 })[0]).toMatch(/khoảng/);
    expect(validateValues(veo, "t2v", { seed: 1.5 }).length).toBeGreaterThan(0);
    expect(validateValues(veo, "t2v", { seed: 5 })).toEqual([]);
  });

  it("restricting rules (array) limit options and coerce invalid values", () => {
    const m: Manifest = { ...veo, constraints: [{ when: { resolution: "4k" }, then: { duration: [6, 8] }, reason: "r" }] };
    const r = resolveConstraints(m, "t2v", { resolution: "4k", duration: 4 });
    expect(r.allowed["duration"]).toEqual([6, 8]);
    expect(r.effective["duration"]).toBe(6);
    expect(r.locked["duration"]).toBeUndefined();
    const d = m.params.find((p) => p.key === "duration");
    expect(d && enumOptions(d, r.allowed)).toEqual([6, 8]);
  });

  it("fixpoint: a forced value can trigger another rule", () => {
    const m: Manifest = {
      ...veo,
      constraints: [
        { when: { resolution: "4k" }, then: { aspect_ratio: "16:9" }, reason: "a" },
        { when: { aspect_ratio: "16:9" }, then: { duration: 6 }, reason: "b" },
      ],
    };
    const r = resolveConstraints(m, "t2v", { resolution: "4k", aspect_ratio: "9:16" });
    expect(r.effective).toMatchObject({ aspect_ratio: "16:9", duration: 6 });
  });

  it("cyclic rules terminate", () => {
    const m: Manifest = {
      ...veo,
      constraints: [
        { when: { duration: 4 }, then: { duration: 6 }, reason: "x" },
        { when: { duration: 6 }, then: { duration: 4 }, reason: "y" },
      ],
    };
    expect(() => resolveConstraints(m, "t2v", { duration: 4 })).not.toThrow();
  });

  it("switching model keeps compatible params only; lite exposes only 1K", () => {
    expect(carryParams({ image_size: "4K", other: 1 }, lite, "t2i")).toEqual({});
    expect(carryParams({ image_size: "1K" }, lite, "t2i")).toEqual({ image_size: "1K" });
    expect(lite.params[0]?.values).toEqual(["1K"]);
  });

  it("infers video mode from filled frame slots", () => {
    expect(inferMode(veo, {}, "t2v")).toBe("t2v");
    expect(inferMode(veo, { first_frame: "a" }, "t2v")).toBe("i2v");
    expect(inferMode(veo, { first_frame: "a", last_frame: "b" }, "t2v")).toBe("first_last");
    expect(inferMode(lite, { first_frame: "a" }, "t2i")).toBe("t2i");
  });
});
