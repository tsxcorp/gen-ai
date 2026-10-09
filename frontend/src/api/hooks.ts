import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api } from "./client";
import type { GenerationRequest, Manifest, Params, ResolveError, ResolveResponse, SweepSpec } from "./types";
import { resolveConstraints, type ResolveResult } from "../lib/constraints";
import { mergeResolveErrors, normalizeServerErrors } from "../lib/resolveErrors";
import { cleanAxes } from "../lib/sweep";

export function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

export const manifestKey = (id: string) => ["manifest", id] as const;

export function useManifests() {
  return useQuery({ queryKey: ["manifests"], queryFn: api.manifests, staleTime: 60_000 });
}

export function useManifest(id: string | null) {
  return useQuery({
    queryKey: manifestKey(id ?? ""),
    queryFn: () => api.manifest(id as string),
    enabled: !!id,
    staleTime: 60_000,
  });
}

export interface Resolved extends Omit<ResolveResult, "errors" | "errorItems"> {
  /** merged local + server errors, always `{key, reason}` with string fields */
  errors: ResolveError[];
  serverPending: boolean;
  serverError: string | null;
  payload?: unknown;
  requestParams?: Params;
}

/** Local constraint engine for instant feedback, confirmed by POST /api/resolve. */
export function useResolved(m: Manifest | undefined, mode: string, params: Params): Resolved {
  const local = useMemo(() => (m ? resolveConstraints(m, mode, params) : null), [m, mode, params]);
  const body = useMemo(() => (m ? { modelId: m.id, mode, params } : null), [m, mode, params]);
  const debounced = useDebounced(body, 250);
  const q = useQuery<ResolveResponse>({
    queryKey: ["resolve", debounced],
    queryFn: () => api.resolve(debounced as NonNullable<typeof debounced>),
    enabled: !!debounced,
    placeholderData: keepPreviousData,
    retry: false,
  });
  return useMemo(() => {
    const base: ResolveResult = local ?? { effective: {}, locked: {}, allowed: {}, errors: [], errorItems: [] };
    const fresh = q.data && debounced === body && !q.isPlaceholderData ? q.data : null;
    const locked = { ...base.locked };
    let errors: ResolveError[] = base.errorItems;
    let effective = base.effective;
    if (fresh) {
      (Array.isArray(fresh.locked) ? fresh.locked : []).forEach((l) => l && typeof l.key === "string" && (locked[l.key] = locked[l.key] ?? String(l.reason)));
      errors = mergeResolveErrors(errors, normalizeServerErrors(fresh.errors));
      effective = { ...base.effective, ...fresh.effectiveParams };
    }
    return {
      allowed: base.allowed,
      effective,
      locked,
      errors,
      serverPending: debounced !== body || q.isFetching,
      serverError: q.error ? (q.error as Error).message : null,
      payload: fresh?.payload,
      requestParams: params,
    };
  }, [local, q.data, q.isFetching, q.isPlaceholderData, q.error, debounced, body]);
}

export function buildSweep(sweep: SweepSpec): SweepSpec {
  return { ...sweep, variants: Math.max(1, Math.floor(sweep.variants) || 1), axes: cleanAxes(sweep.axes) };
}

export function useEstimate(request: GenerationRequest | null, sweep: SweepSpec, enabled: boolean) {
  const sw = useMemo(() => buildSweep(sweep), [sweep]);
  const currentKey = request ? JSON.stringify({ request, sweep: sw }) : null;
  const key = useDebounced(currentKey, 350);
  const result = useQuery({
    queryKey: ["estimate", key],
    queryFn: () => api.estimate(JSON.parse(key as string) as { request: GenerationRequest; sweep: SweepSpec }),
    enabled: enabled && !!request && !!key && key === currentKey,
    retry: false,
  });
  return { ...result, data: enabled && key === currentKey ? result.data : undefined };
}
