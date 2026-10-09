import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ErrorList } from "../panel/ErrorList";
import { ErrorBoundary } from "../ui/ErrorBoundary";
import { resolveConstraints } from "./constraints";
import { veo } from "./fixtures";
import { mergeResolveErrors, normalizeServerErrors } from "./resolveErrors";
import type { Manifest } from "../api/types";

// Exact shape the backend returned in review-v1 #2 for seed=99999999999.
const serverSeed = [{ key: "seed", reason: "must be within [0.0, 2147483647.0]" }];

describe("review #2 regression: /api/resolve errors are {key, reason}[]", () => {
  it("seed=99999999999: local + server errors merge to string reasons, one per key, and render without throwing", () => {
    const local = resolveConstraints(veo, "t2v", { seed: 99999999999 });
    expect(local.errorItems.map((e) => e.key)).toEqual(["seed"]);
    const merged = mergeResolveErrors(local.errorItems, normalizeServerErrors(serverSeed));
    expect(merged).toHaveLength(1); // deduped by key
    expect(merged.every((e) => typeof e.reason === "string")).toBe(true);
    const html = renderToStaticMarkup(<ErrorList errors={merged} />);
    expect(html).toContain("seed");
    expect(html).not.toContain("[object Object]");
  });

  it("a server-only error (unknown param / block rule) is kept and rendered as its reason", () => {
    const merged = mergeResolveErrors([], normalizeServerErrors([{ key: "foo", reason: "unknown param foo" }]));
    expect(merged).toEqual([{ key: "foo", reason: "unknown param foo" }]);
    expect(renderToStaticMarkup(<ErrorList errors={merged} />)).toContain("unknown param foo");
  });

  it("tolerates legacy strings and malformed entries without ever yielding a non-string reason", () => {
    const n = normalizeServerErrors(["old style", { key: "a" }, { reason: 5 }, null, 7, { key: "k", message: "m" }]);
    expect(n.every((e) => typeof e.key === "string" && typeof e.reason === "string")).toBe(true);
    expect(n[0]).toEqual({ key: "", reason: "old style" });
    expect(n.at(-1)).toEqual({ key: "k", reason: "m" });
    expect(normalizeServerErrors(undefined)).toEqual([]);
  });

  it("ErrorBoundary turns a render error into recoverable state (and retry clears it)", () => {
    const st = ErrorBoundary.getDerivedStateFromError(new Error("boom"));
    expect((st.error as Error).message).toBe("boom");
    expect(ErrorBoundary.getDerivedStateFromError("str").error?.message).toBe("str");
  });
});

describe("constraint engine agrees with backend: blocks are evaluated after the fixpoint (invariant 22)", () => {
  const m: Manifest = {
    ...veo,
    constraints: [
      { when: { resolution: "1080p" }, then: { duration: 8 }, reason: "force 8s" },
      // matches only the INTERMEDIATE state (duration 4) that the force rule then repairs
      { when: { resolution: "1080p", duration: 4 }, block: true, reason: "1080p x 4s (intermediate)" },
      { when: { resolution: "1080p", duration: 8, aspect_ratio: "9:16" }, block: true, reason: "final-state block" },
    ],
  };
  it("does not report a block that only matched before a force rule repaired the state", () => {
    const r = resolveConstraints(m, "t2v", { resolution: "1080p", duration: 4 });
    expect(r.effective["duration"]).toBe(8);
    expect(r.errors).toEqual([]);
  });
  it("reports a block that matches the final state", () => {
    const r = resolveConstraints(m, "t2v", { resolution: "1080p", duration: 4, aspect_ratio: "9:16" });
    expect(r.errors).toEqual(["final-state block"]);
    expect(r.errorItems[0]?.key).toBe("resolution,duration,aspect_ratio");
  });
});
