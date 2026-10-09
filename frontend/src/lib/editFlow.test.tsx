import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { Asset, Manifest } from "../api/types";
import { currentRequest, slotIds, useStudio } from "../store/studio";
import { resolveImageSizing } from "./imageSizing";

const manifest: Manifest = {
  id: "edit-flow-fixture", kind: "image", status: "ga", modes: ["t2i", "edit"],
  params: [
    { key: "aspect_ratio", type: "ratio", values: ["1:1", "16:9", "9:16"], default: "1:1" },
    { key: "reference_images", type: "imageList", appliesToModes: ["edit"], level: "advanced" },
  ], constraints: [],
};
const first: Asset = { id: "first", mime: "image/png", name: "first.png", width: 1600, height: 900 };
const second: Asset = { id: "second", mime: "image/png", name: "second.png", width: 900, height: 1600 };
const initial = useStudio.getState();
beforeEach(() => useStudio.setState(initial, true));
afterEach(() => useStudio.setState(initial, true));

describe("edit state flow (architecture Upload và Auto tỷ lệ edit)", () => {
  it("same-model reuse advances requestVersion even when the restored request is identical", () => {
    const request = { mode: "edit", params: { aspect_ratio: "1:1" }, slots: { reference_images: [first] } };
    useStudio.getState().loadRequest(manifest, request);
    const firstVersion = useStudio.getState().requestVersion;
    useStudio.getState().loadRequest(manifest, request);
    expect(useStudio.getState().requestVersion).toBe(firstVersion + 1);
    expect(useStudio.getState().modelId).toBe(manifest.id);
    expect(useStudio.getState().autoImageSizing).toBe(false);
    expect(useStudio.getState().params).toEqual(request.params);
  });
  it("model selection and mode changes each advance the upload lifecycle version", () => {
    let version = useStudio.getState().requestVersion;
    useStudio.getState().selectModel(manifest);
    expect(useStudio.getState().requestVersion).toBe(++version);
    useStudio.getState().selectModel(manifest);
    expect(useStudio.getState().requestVersion).toBe(++version);
    useStudio.getState().setMode(manifest, "edit");
    expect(useStudio.getState().requestVersion).toBe(++version);
    useStudio.getState().setMode(manifest, "t2i");
    expect(useStudio.getState().requestVersion).toBe(++version);
  });
  it("entering edit enables UI Auto without putting a sentinel in params", () => {
    useStudio.getState().selectModel(manifest);
    useStudio.getState().setAutoImageSizing(false);
    useStudio.getState().setMode(manifest, "edit");
    expect(useStudio.getState().autoImageSizing).toBe(true);
    expect(Object.values(useStudio.getState().params)).not.toContain("Auto");
    expect(Object.values(useStudio.getState().params)).not.toContain("auto");
  });
  it("restored preset/reuse remains manual and keeps its concrete saved ratio", () => {
    useStudio.getState().loadRequest(manifest, { mode: "edit", params: { aspect_ratio: "1:1" }, slots: { reference_images: [first] } });
    const state = useStudio.getState();
    expect(state.mode).toBe("edit");
    expect(state.autoImageSizing).toBe(false);
    const result = resolveImageSizing(manifest, state.mode, state.params, state.slots, state.autoImageSizing);
    expect(result.params).toEqual({ aspect_ratio: "1:1" });
    expect(result.error).toBeUndefined();
  });
  it("reading restored dimensions does not turn manual back into Auto", () => {
    useStudio.getState().loadRequest(manifest, { mode: "edit", params: { aspect_ratio: "1:1" }, slots: { reference_images: [{ id: "restored", mime: "image/png" }] } });
    useStudio.getState().setAssetDimensions("restored", { width: 1600, height: 900 });
    expect(useStudio.getState().autoImageSizing).toBe(false);
    expect(useStudio.getState().params).toEqual({ aspect_ratio: "1:1" });
  });
  it("dimension updates preserve source order and do not alter other images", () => {
    useStudio.getState().setSlot(manifest, "reference_images", [first, second]);
    useStudio.getState().setAssetDimensions("first", { width: 800, height: 800 });
    const slots = useStudio.getState().slots;
    expect(slots.reference_images).toEqual([{ ...first, width: 800, height: 800 }, second]);
    expect(first.width).toBe(1600);
    expect(second.width).toBe(900);
  });
  it("source removal recomputes Auto and removing all sources blocks it", () => {
    useStudio.getState().setMode(manifest, "edit");
    useStudio.getState().setSlot(manifest, "reference_images", [second]);
    let state = useStudio.getState();
    expect(resolveImageSizing(manifest, state.mode, state.params, state.slots, state.autoImageSizing).value).toBe("9:16");
    state.setSlot(manifest, "reference_images", null);
    state = useStudio.getState();
    expect(resolveImageSizing(manifest, state.mode, state.params, state.slots, state.autoImageSizing).error).toEqual(expect.any(String));
  });
  it("request assets contain IDs only, never client dimensions or names", () => {
    expect(slotIds({ reference_images: [first, second], single: first })).toEqual({ reference_images: ["first", "second"], single: "first" });
  });
  it("currentRequest uses concrete Auto params and excludes all client-only metadata", () => {
    useStudio.getState().selectModel(manifest);
    useStudio.getState().setMode(manifest, "edit");
    useStudio.getState().setPrompt("Edit the image");
    useStudio.getState().setSlot(manifest, "reference_images", [first, second]);
    const state = useStudio.getState();
    const sizing = resolveImageSizing(manifest, state.mode, state.params, state.slots, state.autoImageSizing);
    const request = currentRequest({ ...state, params: sizing.params });
    expect(request).toEqual({ modelId: manifest.id, mode: "edit", prompt: "Edit the image", params: { aspect_ratio: "16:9" }, assets: { reference_images: ["first", "second"] } });
    const json = JSON.stringify(request);
    for (const metadata of ["width", "height", "name", "first.png", "autoImageSizing"]) expect(json).not.toContain(metadata);
  });
  it("updates matching dimensions in scalar slots and ignores stale asset IDs", () => {
    useStudio.getState().setSlot(undefined, "single", first);
    useStudio.getState().setAssetDimensions("missing", { width: 12, height: 24 });
    expect(useStudio.getState().slots.single).toEqual(first);
    useStudio.getState().setAssetDimensions("first", { width: 800, height: 800 });
    expect(useStudio.getState().slots.single).toEqual({ ...first, width: 800, height: 800 });
  });
  it("model switch and leaving edit do not retain incompatible parameters", () => {
    useStudio.getState().loadRequest(manifest, { mode: "edit", params: { aspect_ratio: "16:9" }, slots: { reference_images: [first] } });
    useStudio.getState().setMode(manifest, "t2i");
    expect(useStudio.getState().autoImageSizing).toBe(false);
    const other: Manifest = { ...manifest, id: "other-fixture", params: [{ key: "aspect_ratio", type: "ratio", values: ["1:1"] }] };
    useStudio.getState().selectModel(other);
    expect(useStudio.getState().slots).toEqual({});
    expect(useStudio.getState().params).not.toHaveProperty("aspect_ratio", "16:9");
  });
});
