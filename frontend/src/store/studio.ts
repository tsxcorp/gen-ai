import { create } from "zustand";
import type { Asset, AssetSlots, GenerationRequest, Job, Manifest, Params, ProviderId, SweepSpec } from "../api/types";
import { carryParams, inferMode, pickMode, pruneParams } from "../lib/constraints";
import { isActive, unsavedFor } from "../lib/job";
import { emptySweep } from "../lib/sweep";

export type Page = "studio" | "settings";
export type SlotAssets = Record<string, Asset | Asset[]>;

export interface BatchMeta {
  id: string;
  createdAt: number;
  jobIds: string[];
  /** request used to create it (fallback for Reuse when a job lacks prompt/assets) */
  request: GenerationRequest;
}

interface StudioState {
  page: Page;
  /** provider tab opened on the settings page ("Cài đặt" links jump here) */
  settingsProvider: ProviderId;
  modelId: string | null;
  mode: string;
  prompt: string;
  params: Params;
  autoImageSizing: boolean;
  requestVersion: number;
  slots: SlotAssets;
  sweep: SweepSpec;
  promptListText: string;
  rawOverride: string | null;

  jobs: Record<string, Job>;
  batches: BatchMeta[]; // newest first
  selected: string[]; // job ids
  downloaded: Record<string, true>; // asset ids
  sseConnected: boolean;
  compareOpen: boolean;

  setPage: (p: Page) => void;
  openSettings: (p: ProviderId) => void;
  setSettingsProvider: (p: ProviderId) => void;
  setPrompt: (p: string) => void;
  setParam: (key: string, v: Params[string] | undefined) => void;
  setAutoImageSizing: (auto: boolean) => void;
  setAssetDimensions: (id: string, dimensions: { width: number; height: number }) => void;
  setMode: (manifest: Manifest, mode: string) => void;
  setSlot: (manifest: Manifest | undefined, slot: string, a: Asset | Asset[] | null) => void;
  setSweep: (patch: Partial<SweepSpec>) => void;
  setPromptListText: (t: string) => void;
  replaceParams: (params: Params) => void;
  /** switch model keeping prompt + compatible params/slots */
  selectModel: (m: Manifest) => void;
  /** load a full request (Reuse/Vary, preset, Make video) */
  loadRequest: (m: Manifest, r: { mode?: string; params?: Params; prompt?: string; slots?: SlotAssets }) => void;

  addBatch: (meta: BatchMeta, jobs: Job[]) => void;
  upsertJob: (j: Job) => void;
  toggleSelect: (id: string) => void;
  clearSelection: () => void;
  markDownloaded: (assetIds: string[]) => void;
  setSse: (c: boolean) => void;
  setCompare: (o: boolean) => void;
}

export function slotIds(slots: SlotAssets): AssetSlots {
  const out: AssetSlots = {};
  for (const [k, v] of Object.entries(slots)) {
    if (Array.isArray(v)) {
      if (v.length) out[k] = v.map((a) => a.id);
    } else out[k] = v.id;
  }
  return out;
}

export const useStudio = create<StudioState>((set) => ({
  page: "studio",
  settingsProvider: "vertex",
  modelId: null,
  mode: "default",
  prompt: "",
  params: {},
  autoImageSizing: true,
  requestVersion: 0,
  slots: {},
  sweep: emptySweep(),
  promptListText: "",
  rawOverride: null,
  jobs: {},
  batches: [],
  selected: [],
  downloaded: {},
  sseConnected: false,
  compareOpen: false,

  setPage: (page) => set({ page }),
  openSettings: (p) => set({ page: "settings", settingsProvider: p }),
  setSettingsProvider: (p) => set({ settingsProvider: p }),
  setPrompt: (prompt) => set({ prompt }),
  setParam: (key, v) =>
    set((s) => {
      const params = { ...s.params };
      if (v === undefined) delete params[key];
      else params[key] = v;
      return { params };
    }),
  setAutoImageSizing: (autoImageSizing) => set({ autoImageSizing }),
  setAssetDimensions: (id, dimensions) => set((state) => ({
    slots: Object.fromEntries(Object.entries(state.slots).map(([key, assets]) => [key,
      Array.isArray(assets) ? assets.map((asset) => asset.id === id ? { ...asset, ...dimensions } : asset)
        : assets.id === id ? { ...assets, ...dimensions } : assets,
    ])),
  })),
  setMode: (m, mode) =>
    set((s) => ({ mode, params: pruneParams(m, mode, s.params), autoImageSizing: mode === "edit", requestVersion: s.requestVersion + 1 })),
  setSlot: (m, slot, a) =>
    set((s) => {
      const slots = { ...s.slots };
      if (a === null || (Array.isArray(a) && a.length === 0)) delete slots[slot];
      else slots[slot] = a;
      const mode = m ? inferMode(m, slots, s.mode) : s.mode;
      return { slots, mode };
    }),
  setSweep: (patch) => set((s) => ({ sweep: { ...s.sweep, ...patch } })),
  setPromptListText: (promptListText) => set({ promptListText }),
  replaceParams: (params) => set({ params }),

  selectModel: (m) =>
    set((s) => {
      const mode = pickMode(m, s.mode);
      const keepSlots: SlotAssets = {};
      for (const p of m.params) {
        const v = s.slots[p.key];
        if (v && (p.type === "image" || p.type === "imageList") && p.supported !== false) keepSlots[p.key] = v;
      }
      const axes = s.sweep.axes.filter((a) => m.params.some((p) => p.key === a.param && p.supported !== false));
      return {
        modelId: m.id,
        autoImageSizing: true,
        requestVersion: s.requestVersion + 1,
        mode: inferMode(m, keepSlots, mode),
        params: carryParams(s.params, m, mode),
        slots: keepSlots,
        sweep: { ...s.sweep, axes },
      };
    }),
  loadRequest: (m, r) =>
    set((s) => {
      const slots = r.slots ?? {};
      const mode0 = pickMode(m, r.mode);
      const mode = inferMode(m, slots, mode0);
      return {
        modelId: m.id,
        autoImageSizing: false,
        requestVersion: s.requestVersion + 1,
        mode,
        params: pruneParams(m, mode, r.params ?? {}),
        prompt: r.prompt ?? s.prompt,
        slots,
        // a loaded request is a single job: never carry an old sweep (could multiply cost / name foreign params)
        sweep: emptySweep(),
        promptListText: "",
        page: "studio",
      };
    }),

  addBatch: (meta, jobs) =>
    set((s) => {
      const nj = { ...s.jobs };
      for (const j of jobs) nj[j.id] = j;
      // SSE may have created a synthetic group for this batch before the POST returned: replace it.
      const others = s.batches.filter((b) => b.id !== meta.id);
      const early = s.batches.find((b) => b.id === meta.id)?.jobIds ?? [];
      const ids = [...new Set([...jobs.map((j) => j.id), ...early])];
      return { jobs: nj, batches: [{ ...meta, jobIds: ids }, ...others] };
    }),
  upsertJob: (j) =>
    set((s) => {
      const prev = s.jobs[j.id];
      // invariant 4: states are monotonic; ignore a stale event that would move a terminal job back.
      if (prev && !isActive(prev.status) && isActive(j.status)) return s;
      const jobs = { ...s.jobs, [j.id]: { ...prev, ...j } };
      let batches = s.batches;
      const bi = batches.findIndex((b) => b.id === j.batchId);
      if (bi >= 0) {
        const b = batches[bi] as BatchMeta;
        if (!b.jobIds.includes(j.id)) {
          batches = batches.slice();
          batches[bi] = { ...b, jobIds: [...b.jobIds, j.id] };
        }
      } else if (j.batchId) {
        // job from a retry / another tab: show it in a synthetic batch group
        batches = [
          {
            id: j.batchId,
            createdAt: Date.now(),
            jobIds: [j.id],
            request: { modelId: j.modelId, mode: j.mode ?? "", params: j.requestedParams, prompt: j.prompt ?? "", assets: j.assetsIn ?? {} },
          },
          ...batches,
        ];
      }
      return { jobs, batches };
    }),
  toggleSelect: (id) =>
    set((s) => ({ selected: s.selected.includes(id) ? s.selected.filter((x) => x !== id) : [...s.selected, id] })),
  clearSelection: () => set({ selected: [] }),
  markDownloaded: (ids) =>
    set((s) => {
      const d = { ...s.downloaded };
      ids.forEach((i) => (d[i] = true));
      return { downloaded: d };
    }),
  setSse: (sseConnected) => set({ sseConnected }),
  setCompare: (compareOpen) => set({ compareOpen }),
}));

export function currentRequest(s: Pick<StudioState, "modelId" | "mode" | "prompt" | "params" | "slots">): GenerationRequest | null {
  if (!s.modelId) return null;
  return { modelId: s.modelId, mode: s.mode, params: s.params, prompt: s.prompt, assets: slotIds(s.slots) };
}

export function hasRunning(jobs: Record<string, Job>): boolean {
  return Object.values(jobs).some((j) => isActive(j.status));
}
export function unsavedAssetIds(jobs: Record<string, Job>, downloaded: Record<string, true>): string[] {
  return unsavedFor(Object.values(jobs), downloaded);
}
