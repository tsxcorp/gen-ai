import type { QueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { manifestKey } from "../api/hooks";
import type { Asset, Job, ManifestSummary } from "../api/types";
import { jobPrompt } from "../lib/job";
import { useStudio, type BatchMeta } from "../store/studio";

const fetchManifest = (qc: QueryClient, id: string) =>
  qc.fetchQuery({ queryKey: manifestKey(id), queryFn: () => api.manifest(id), staleTime: 60_000 });

/** Reuse/Vary: load requestedParams (+ prompt, input assets) into the panel; no API call (flow 5). */
export async function reuseJob(qc: QueryClient, job: Job, batch?: BatchMeta): Promise<void> {
  const m = await fetchManifest(qc, job.modelId);
  const assetIds = job.assetsIn ?? batch?.request.assets ?? {};
  // We only know ids for input assets; build minimal Asset records (mime unknown => image).
  const slots: Record<string, Asset | Asset[]> = {};
  for (const [slot, v] of Object.entries(assetIds)) {
    const mk = (id: string): Asset => ({ id, mime: "image/*", kind: "upload" });
    slots[slot] = Array.isArray(v) ? v.map(mk) : mk(v);
  }
  useStudio.getState().loadRequest(m, {
    mode: job.mode ?? batch?.request.mode,
    params: job.requestedParams,
    prompt: jobPrompt(job) || batch?.request.prompt || "",
    slots,
  });
}

/** Story 8: image -> video panel, image in first_frame / last_frame slot. */
export async function makeVideo(qc: QueryClient, models: ManifestSummary[], job: Job, asset: Asset, slot: "first_frame" | "last_frame"): Promise<string | null> {
  const cur = useStudio.getState().modelId;
  const curSummary = models.find((x) => x.id === cur);
  const target = curSummary?.kind === "video" ? curSummary : models.find((x) => x.kind === "video");
  if (!target) return "Không có model video nào";
  const m = await fetchManifest(qc, target.id);
  if (!m.params.some((p) => p.key === slot && p.supported !== false)) {
    return `Model ${m.id} không có slot ${slot}`;
  }
  const st = useStudio.getState();
  const slots = { ...(st.modelId === m.id ? st.slots : {}), [slot]: asset };
  st.loadRequest(m, { prompt: jobPrompt(job) || st.prompt, params: st.modelId === m.id ? st.params : {}, slots });
  return null;
}
