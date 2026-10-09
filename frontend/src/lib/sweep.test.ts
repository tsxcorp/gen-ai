import { describe, expect, it } from "vitest";
import type { GenerationRequest, SweepSpec } from "../api/types";
import { cleanAxes, countJobs, emptySweep, expandCells, footerLabel, formatRange, isStalePrice, needsConfirm, parseAxisValues, parsePromptList } from "./sweep";
import { modelWarnings } from "./manifestMeta";

const base: GenerationRequest = { modelId: "m", mode: "t2i", params: { a: 1 }, prompt: "p", assets: {} };
const sw = (p: Partial<SweepSpec>): SweepSpec => ({ ...emptySweep(), ...p });

describe("sweep", () => {
  it("N variants = N jobs", () => expect(countJobs(sw({ variants: 6 }))).toBe(6));
  it("story 3: 3 prompts x 2 axes (3x2) = 18 jobs with N=1... prompts*axes*N", () => {
    const s = sw({ prompts: ["a", "b", "c"], axes: [{ param: "q", values: ["lo", "hi"] }, { param: "r", values: ["1:1", "16:9", "9:16"] }] });
    expect(countJobs(s)).toBe(18);
    expect(countJobs({ ...s, variants: 2 })).toBe(36);
  });
  it("caps at two axes and drops empty/duplicate values", () => {
    const axes = cleanAxes([
      { param: "a", values: [1, 1, 2] },
      { param: "", values: [1] },
      { param: "b", values: [] },
      { param: "c", values: [1] },
      { param: "d", values: [1] },
    ]);
    expect(axes).toEqual([{ param: "a", values: [1, 2] }, { param: "c", values: [1] }]);
  });
  it("parses prompt list and axis values", () => {
    expect(parsePromptList(" a \n\n b\r\nc ")).toEqual(["a", "b", "c"]);
    expect(parseAxisValues("4, 6;8", "int")).toEqual([4, 6, 8]);
    expect(parseAxisValues("1K, 2K", "enum")).toEqual(["1K", "2K"]);
  });
  it("expands the prompt x axes grid, falling back to the base prompt", () => {
    const cells = expandCells(base, sw({ axes: [{ param: "q", values: ["lo", "hi"] }] }));
    expect(cells).toEqual([
      { prompt: "p", params: { a: 1, q: "lo" } },
      { prompt: "p", params: { a: 1, q: "hi" } },
    ]);
    expect(expandCells(base, sw({ prompts: ["x", "y"] })).map((c) => c.prompt)).toEqual(["x", "y"]);
  });
  it("count matches expansion size", () => {
    const s = sw({ prompts: ["x", "y"], axes: [{ param: "q", values: [1, 2, 3] }] });
    expect(expandCells(base, s)).toHaveLength(countJobs(s));
  });
});

describe("estimate display", () => {
  it("formats ranges and footer", () => {
    expect(formatRange(0.4, 0.4)).toBe("$0.40");
    expect(formatRange(0.2, 0.8)).toBe("$0.20–$0.80");
    expect(footerLabel(18, { minUsd: 1, maxUsd: 2.5 })).toBe("18 job · $1.00–$2.50");
    expect(footerLabel(3, null)).toBe("3 job · …");
  });
  it("needsConfirm prefers backend flag, else threshold", () => {
    expect(needsConfirm(null)).toBe(false);
    expect(needsConfirm({ jobCount: 1, minUsd: 0, maxUsd: 9, confirmRequired: false })).toBe(false);
    expect(needsConfirm({ jobCount: 1, minUsd: 0, maxUsd: 9, thresholdUsd: 5 })).toBe(true);
    expect(needsConfirm({ jobCount: 1, minUsd: 0, maxUsd: 4, thresholdUsd: 5 })).toBe(false);
  });
});

describe("staleness (invariant 9)", () => {
  const now = new Date("2026-10-07");
  it("stale after 30 days or when missing", () => {
    expect(isStalePrice("2026-10-01", now)).toBe(false);
    expect(isStalePrice("2026-08-01", now)).toBe(true);
    expect(isStalePrice(null, now)).toBe(true);
  });
  it("deprecated and sunset always warn", () => {
    const w = modelWarnings({ status: "deprecated", sunsetDate: "2026-11-17", lastVerified: "2026-10-07" }, now);
    expect(w[0]?.level).toBe("danger");
    expect(modelWarnings({ status: "ga", lastVerified: "2026-10-07" }, now)).toEqual([]);
  });
});
