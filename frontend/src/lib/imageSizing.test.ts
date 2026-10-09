import { describe, expect, it } from "vitest";
import type { Asset, Manifest, ParamDef, Scalar } from "../api/types";
import { chooseAspectRatio, chooseImageSize, resolveImageSizing, validDimensions } from "./imageSizing";

const ratios: Scalar[] = ["adaptive", "1:1", "4:3", "3:4", "16:9", "9:16"];
const ratioManifest: Manifest = {
  id: "sizing-fixture", kind: "image", status: "ga", modes: ["t2i", "edit"],
  params: [
    { key: "aspect_ratio", type: "ratio", values: ratios, default: "1:1", group: "size" },
    { key: "reference_images", type: "imageList", appliesToModes: ["edit"], maxItems: 3 },
  ],
  constraints: [],
};
const sizeParam = {
  key: "size", type: "text", default: "1024x1024", group: "size",
  sizeRule: { allow: ["auto"], multipleOf: 16, maxEdge: 3840, maxRatio: 3, minPixels: 655360, maxPixels: 8294400 },
} satisfies ParamDef & { sizeRule: Record<string, unknown> };
const smallSizeParam: ParamDef = {
  key: "size", type: "text", default: "64x64",
  sizeRule: { multipleOf: 16, maxEdge: 64, maxRatio: 2, minPixels: 512, maxPixels: 4096 },
};
const source = (id: string, width?: number, height?: number): Asset & { width?: number; height?: number; name: string } =>
  ({ id, mime: "image/png", kind: "upload", width, height, name: `${id}.png` });

describe("edit aspect ratio selection (requirements #11)", () => {
  it.each([[1600, 900, "16:9"], [900, 1600, "9:16"], [800, 800, "1:1"], [1200, 900, "4:3"]])(
    "preserves exact %sx%s as %s", (width, height, value) => {
      expect(chooseAspectRatio(Number(width), Number(height), ratios)).toEqual({ value, exact: true });
    },
  );
  it("chooses nearest by relative logarithmic error, not absolute distance", () => {
    expect(chooseAspectRatio(1400, 1000, ["1:1", "2:1"])).toEqual({ value: "1:1", exact: false });
    expect(chooseAspectRatio(1000, 1400, ratios)).toEqual({ value: "3:4", exact: false });
  });
  it("resolves equally close ratio choices deterministically", () => {
    const values: Scalar[] = ["1:1", "4:1"];
    const firstChoice = chooseAspectRatio(200, 100, values);
    expect(firstChoice?.exact).toBe(false);
    expect(values).toContain(firstChoice?.value);
    for (let repeat = 0; repeat < 5; repeat += 1) expect(chooseAspectRatio(200, 100, values)).toEqual(firstChoice);
  });
  it("ignores sentinels and malformed or nonpositive ratio options", () => {
    expect(chooseAspectRatio(1600, 900, ["auto", "adaptive", "0:1", "1:0", "-1:2", "broken", true, 42, "16:9"]))
      .toEqual({ value: "16:9", exact: true });
    expect(chooseAspectRatio(1600, 900, ["auto", "adaptive", "broken", "0:0", false, 12])).toBeNull();
    expect(chooseAspectRatio(1600, 900, [])).toBeNull();
  });
  it.each([[0, 900], [1600, 0], [-1, 100], [100, -1], [NaN, 100], [100, NaN], [Infinity, 100], [100, Infinity]])(
    "rejects unreadable dimensions %sx%s", (width, height) => {
      expect(chooseAspectRatio(width, height, ratios)).toBeNull();
      expect(chooseImageSize(width, height, sizeParam)).toBeNull();
    },
  );
});

describe("manifest-driven WxH sizing", () => {
  it("honors allowed WxH values instead of inventing an exact square", () => {
    const allowed: Scalar[] = ["32x64", "64x32"];
    const result = chooseImageSize(100, 100, smallSizeParam, allowed);
    expect(result).not.toBeNull();
    expect(allowed).toContain(result?.value);
    expect(result?.value).not.toBe("64x64");
    expect(result?.exact).toBe(false);
    expect(allowed).toEqual(["32x64", "64x32"]);
  });
  it("does not fall back when allowed sizes are empty or all invalid", () => {
    expect(chooseImageSize(100, 100, smallSizeParam, [])).toBeNull();
    expect(chooseImageSize(100, 100, smallSizeParam, ["auto", "broken", "17x32", "80x80", "16x64", false])).toBeNull();
  });
  it.each([[1, 1], [16, 9], [9, 16], [7, 5], [5, 7], [100, 1], [1, 100]])(
    "matches an exhaustive small-grid sizing oracle for %s:%s", (width, height) => {
      const edges = [16, 32, 48, 64];
      const candidates = edges.flatMap((candidateWidth) => edges.map((candidateHeight) => ({
        width: candidateWidth, height: candidateHeight,
        ratioError: Math.abs(Math.log((candidateWidth / candidateHeight) / (width / height))),
        areaError: Math.abs(Math.log(candidateWidth * candidateHeight / (64 * 64))),
      }))).filter((candidate) => candidate.width * candidate.height >= 512 &&
        Math.max(candidate.width / candidate.height, candidate.height / candidate.width) <= 2);
      candidates.sort((first, second) => Math.abs(first.ratioError - second.ratioError) > 1e-12
        ? first.ratioError - second.ratioError : first.areaError - second.areaError);
      const best = candidates[0]!;
      const result = chooseImageSize(width, height, smallSizeParam);
      expect(result).not.toBeNull();
      const [outWidth = 0, outHeight = 0] = (result?.value ?? "").split("x").map(Number);
      expect(candidates.some((candidate) => candidate.width === outWidth && candidate.height === outHeight)).toBe(true);
      expect(Math.abs(Math.log((outWidth / outHeight) / (width / height)))).toBeCloseTo(best.ratioError, 10);
      expect(Math.abs(Math.log(outWidth * outHeight / (64 * 64)))).toBeCloseTo(best.areaError, 10);
    },
  );
  const numericBounds = ["multipleOf", "maxEdge", "maxRatio", "minPixels", "maxPixels"] as const;
  const invalidBounds = numericBounds.flatMap((key) => [NaN, Infinity, -Infinity, -1, 0].map((value) => ({ key, value })));
  it.each(invalidBounds)("rejects malformed $key=$value before size search", ({ key, value }) => {
    const param: ParamDef = { ...smallSizeParam, sizeRule: { ...smallSizeParam.sizeRule, [key]: value } };
    expect(chooseImageSize(100, 100, param)).toBeNull();
    expect(chooseImageSize(100, 100, param, ["32x64", "64x32"])).toBeNull();
  });
  it.each([
    { minPixels: 4097, maxPixels: 4096 },
    { minPixels: 8192 },
    { multipleOf: 128 },
    { maxRatio: 0.5 },
    { multipleOf: 1.5 },
    { maxEdge: 64.5 },
  ])("rejects inconsistent or nonintegral bounds %j", (bounds) => {
    expect(chooseImageSize(100, 100, { ...smallSizeParam, sizeRule: { ...smallSizeParam.sizeRule, ...bounds } })).toBeNull();
  });
  it("keeps the default area for a square", () => {
    expect(chooseImageSize(800, 800, sizeParam)).toEqual({ value: "1024x1024", exact: true });
  });
  it.each([[1600, 900], [900, 1600], [10000, 1], [1, 10000], [997, 613]])(
    "returns only sizes satisfying every sizeRule for %sx%s", (width, height) => {
      const result = chooseImageSize(width, height, sizeParam);
      expect(result).not.toBeNull();
      expect(result?.value).toMatch(/^\d+x\d+$/);
      const [outWidth = 0, outHeight = 0] = (result?.value ?? "").split("x").map(Number);
      expect(outWidth % 16).toBe(0);
      expect(outHeight % 16).toBe(0);
      expect(Math.max(outWidth, outHeight)).toBeLessThanOrEqual(3840);
      expect(Math.max(outWidth, outHeight) / Math.min(outWidth, outHeight)).toBeLessThanOrEqual(3);
      expect(outWidth * outHeight).toBeGreaterThanOrEqual(655360);
      expect(outWidth * outHeight).toBeLessThanOrEqual(8294400);
      expect(result?.exact).toBe(outWidth * height === outHeight * width);
    },
  );
  it("uses supplied bounds rather than hardcoding the OpenAI limits", () => {
    const param = { ...sizeParam, default: "256x256", sizeRule: { multipleOf: 32, maxEdge: 256, maxRatio: 2, minPixels: 32768, maxPixels: 65536 } };
    const result = chooseImageSize(1000, 1000, param);
    expect(result).toEqual({ value: "256x256", exact: true });
  });
  it("reports no valid size for impossible bounds", () => {
    const param = { ...sizeParam, sizeRule: { ...sizeParam.sizeRule, maxEdge: 16 } };
    expect(chooseImageSize(800, 800, param)).toBeNull();
  });
  it("accepts exact sizeRule boundaries inclusively", () => {
    const param = { ...sizeParam, default: "3840x1280", sizeRule: { multipleOf: 16, maxEdge: 3840, maxRatio: 3, minPixels: 4915200, maxPixels: 4915200 } };
    expect(chooseImageSize(3000, 1000, param)).toEqual({ value: "3840x1280", exact: true });
  });
  it("does not invent WxH sizing rules for unrelated text parameters", () => {
    expect(chooseImageSize(800, 800, { key: "prompt", type: "text" })).toBeNull();
  });
});

describe("Auto edit sizing resolution", () => {
  it("uses the first uploaded source and preserves unrelated parameters without mutation", () => {
    const first = source("first", 1600, 900);
    const params = { aspect_ratio: "1:1", seed: 7 };
    const slots = { reference_images: [first, source("second", 900, 1600)] };
    const result = resolveImageSizing(ratioManifest, "edit", params, slots, true);
    expect(result).toMatchObject({ params: { aspect_ratio: "16:9", seed: 7 }, key: "aspect_ratio", value: "16:9", source: first });
    expect(result.error).toBeUndefined();
    expect(result.approximate).not.toBe(true);
    expect(params).toEqual({ aspect_ratio: "1:1", seed: 7 });
    expect(slots.reference_images[0]).toBe(first);
  });
  it("recomputes after first-source removal or replacement", () => {
    const params = { aspect_ratio: "16:9" };
    expect(resolveImageSizing(ratioManifest, "edit", params, { reference_images: [source("portrait", 900, 1600)] }, true).value).toBe("9:16");
    expect(resolveImageSizing(ratioManifest, "edit", params, { reference_images: [source("square", 800, 800)] }, true).value).toBe("1:1");
  });
  it("warns explicitly when only an approximate ratio is supported", () => {
    const result = resolveImageSizing(ratioManifest, "edit", {}, { reference_images: [source("odd", 997, 613)] }, true);
    expect(result.value).toBe("16:9");
    expect(result.approximate).toBe(true);
    expect(result.note).toEqual(expect.any(String));
    expect(result.note?.trim().length).toBeGreaterThan(0);
    expect(result.error).toBeUndefined();
  });
  it.each<Record<string, Asset | Asset[]>>([{}, { reference_images: [] }, { reference_images: [source("unreadable")] }, { reference_images: [source("invalid", 0, 900)] }])(
    "blocks Auto without a readable source", (slots) => {
      const result = resolveImageSizing(ratioManifest, "edit", { aspect_ratio: "1:1" }, slots, true);
      expect(result.error).toEqual(expect.any(String));
      expect(result.error?.trim().length).toBeGreaterThan(0);
    },
  );
  it("does not silently skip the unreadable first source", () => {
    const result = resolveImageSizing(ratioManifest, "edit", {}, { reference_images: [source("bad"), source("good", 1600, 900)] }, true);
    expect(result.error).toEqual(expect.any(String));
  });
  it("blocks when ratio options contain no concrete supported ratios", () => {
    const manifest: Manifest = { ...ratioManifest, params: [{ ...ratioManifest.params[0]!, values: ["adaptive", "auto"] }, ratioManifest.params[1]!] };
    const result = resolveImageSizing(manifest, "edit", {}, { reference_images: [source("image", 1600, 900)] }, true);
    expect(result.error).toEqual(expect.any(String));
    expect(result.value).toBeUndefined();
  });
  it("leaves manual selection untouched even when there is no image", () => {
    const params = { aspect_ratio: "3:4", seed: 11 };
    expect(resolveImageSizing(ratioManifest, "edit", params, {}, false)).toMatchObject({ params });
    expect(resolveImageSizing(ratioManifest, "edit", params, {}, false).error).toBeUndefined();
  });
  it("does not affect video or text-to-image requests", () => {
    const params = { aspect_ratio: "9:16" };
    expect(resolveImageSizing(ratioManifest, "t2i", params, {}, true)).toMatchObject({ params });
    expect(resolveImageSizing(ratioManifest, "t2i", params, {}, true).error).toBeUndefined();
    const video: Manifest = { ...ratioManifest, kind: "video", modes: ["i2v"] };
    const result = resolveImageSizing(video, "i2v", params, { reference_images: [source("image", 1600, 900)] }, true);
    expect(result.params).toEqual(params);
    expect(result.error).toBeUndefined();
  });
  it("resolves size-based edit to concrete WxH, never a sentinel", () => {
    const manifest: Manifest = { ...ratioManifest, params: [sizeParam, ratioManifest.params[1]!] };
    const result = resolveImageSizing(manifest, "edit", { size: "auto" }, { reference_images: [source("square", 800, 800)] }, true);
    expect(result).toMatchObject({ key: "size", value: "1024x1024", params: { size: "1024x1024" } });
    expect(result.error).toBeUndefined();
  });
  it("blocks Auto when the sizeRule admits no valid output", () => {
    const impossible = { ...sizeParam, sizeRule: { ...sizeParam.sizeRule, maxEdge: 16 } };
    const manifest: Manifest = { ...ratioManifest, params: [impossible, ratioManifest.params[1]!] };
    const result = resolveImageSizing(manifest, "edit", {}, { reference_images: [source("square", 800, 800)] }, true);
    expect(result.error).toEqual(expect.any(String));
    expect(result.value).toBeUndefined();
  });
  it("uses currently allowed ratio values, not unrestricted manifest values", () => {
    const manifest: Manifest = { ...ratioManifest, constraints: [{ when: { mode: "edit" }, then: { aspect_ratio: ["1:1", "4:3"] }, reason: "Fixture restriction" }] };
    const result = resolveImageSizing(manifest, "edit", {}, { reference_images: [source("wide", 1600, 900)] }, true);
    expect(result.value).toBe("4:3");
    expect(result.approximate).toBe(true);
    expect(result.note).toEqual(expect.any(String));
  });
  it("uses constraint-restricted WxH options and warns for a square source", () => {
    const manifest: Manifest = {
      ...ratioManifest, params: [smallSizeParam, ratioManifest.params[1]!],
      constraints: [{ when: { mode: "edit" }, then: { size: ["32x64", "64x32"] }, reason: "Fixture size restriction" }],
    };
    const result = resolveImageSizing(manifest, "edit", { size: "64x64" }, { reference_images: [source("square", 100, 100)] }, true);
    expect(["32x64", "64x32"]).toContain(result.value);
    expect(result.params.size).toBe(result.value);
    expect(result.approximate).toBe(true);
    expect(result.note).toEqual(expect.any(String));
    expect(result.error).toBeUndefined();
  });
  it.each(["auto", "17x32", "80x80", "16x64"])("blocks invalid forced WxH %s rather than submitting it", (forced) => {
    const manifest: Manifest = {
      ...ratioManifest, params: [smallSizeParam, ratioManifest.params[1]!],
      constraints: [{ when: { mode: "edit" }, then: { size: forced }, reason: "Fixture invalid forced size" }],
    };
    const result = resolveImageSizing(manifest, "edit", {}, { reference_images: [source("square", 100, 100)] }, true);
    expect(result.error).toEqual(expect.any(String));
    expect(result.value).toBeUndefined();
  });
  it("honors a valid forced WxH and reports approximate sizing", () => {
    const manifest: Manifest = {
      ...ratioManifest, params: [smallSizeParam, ratioManifest.params[1]!],
      constraints: [{ when: { mode: "edit" }, then: { size: "32x64" }, reason: "Fixture forced size" }],
    };
    const result = resolveImageSizing(manifest, "edit", {}, { reference_images: [source("square", 100, 100)] }, true);
    expect(result).toMatchObject({ value: "32x64", params: { size: "32x64" }, approximate: true });
    expect(result.error).toBeUndefined();
    expect(result.note).toContain("Fixture forced size");
  });
  it("respects a forced ratio with an explicit approximation warning", () => {
    const manifest: Manifest = { ...ratioManifest, constraints: [{ when: { mode: "edit" }, then: { aspect_ratio: "1:1" }, reason: "Fixture forced square" }] };
    const result = resolveImageSizing(manifest, "edit", {}, { reference_images: [source("wide", 1600, 900)] }, true);
    expect(result).toMatchObject({ value: "1:1", params: { aspect_ratio: "1:1" }, approximate: true });
    expect(result.note).toContain("Fixture forced square");
  });
});

describe("client image dimensions", () => {
  it.each([[0, 900], [-1, 900], [NaN, 900], [Infinity, 900], [1600, 0], [1600, -1], [1600, NaN], [1600, Infinity]])(
    "flags invalid metadata %sx%s for re-decoding", (width, height) => {
      expect(validDimensions(width, height)).toBe(false);
    },
  );
  it("accepts finite positive dimensions", () => {
    expect(validDimensions(1600, 900)).toBe(true);
    expect(validDimensions(1, 1)).toBe(true);
  });
});
