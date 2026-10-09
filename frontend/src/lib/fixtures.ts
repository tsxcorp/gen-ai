import type { Manifest } from "../api/types";

/** Test-only fixture mirroring requirements "Veo 3.1" (never imported by app code). */
export const veo: Manifest = {
  id: "veo-3.1",
  kind: "video",
  status: "ga",
  lastVerified: "2026-10-07",
  modes: ["t2v", "i2v", "first_last"],
  params: [
    { key: "prompt", type: "text", providerPath: "instances.0.prompt", level: "basic" },
    { key: "aspect_ratio", type: "ratio", values: ["16:9", "9:16"], default: "16:9", level: "basic", group: "size", providerPath: "parameters.aspectRatio" },
    { key: "resolution", type: "enum", values: ["720p", "1080p", "4k"], default: "720p", level: "basic", group: "size", providerPath: "parameters.resolution" },
    { key: "duration", type: "enum", values: [4, 6, 8], default: 8, level: "basic", group: "size", providerPath: "parameters.durationSeconds" },
    { key: "seed", type: "int", range: { min: 0, max: 4294967295 }, level: "advanced", group: "output", providerPath: "parameters.seed" },
    { key: "negative_prompt", type: "text", level: "advanced", group: "style", providerPath: "parameters.negativePrompt" },
    { key: "legacy", type: "text", supported: false, providerPath: "parameters.legacy" },
    { key: "first_frame", type: "image", group: "reference", appliesToModes: ["i2v", "first_last"] },
    { key: "last_frame", type: "image", group: "reference", appliesToModes: ["first_last"] },
  ],
  constraints: [
    { when: { resolution: ["1080p", "4k"] }, then: { duration: 8 }, reason: "Veo ép 8s khi 1080p/4k" },
    { when: { resolution: "4k", aspect_ratio: "9:16" }, block: true, reason: "4k không hỗ trợ 9:16 (fixture)" },
  ],
};

export const lite: Manifest = {
  id: "nb-lite",
  kind: "image",
  status: "preview",
  lastVerified: "2026-10-07",
  modes: ["t2i"],
  params: [{ key: "image_size", type: "enum", values: ["1K"], default: "1K", level: "basic", group: "size" }],
  constraints: [],
};
