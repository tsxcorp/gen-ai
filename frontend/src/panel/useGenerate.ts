import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import { useQueryClient } from "@tanstack/react-query";
import { buildSweep, useEstimate, useManifests, type Resolved } from "../api/hooks";
import type { EstimateResponse, GenerationRequest, SweepSpec } from "../api/types";
import { notConfiguredMessage, providerOf } from "../lib/providers";
import { countJobs, needsConfirm, parsePromptList, sweepConflict } from "../lib/sweep";
import { currentRequest, useStudio } from "../store/studio";

export interface PendingConfirm {
  est: Pick<EstimateResponse, "jobCount" | "minUsd" | "maxUsd" | "thresholdUsd">;
  signature: string;
}

export function useEffectiveSweep(): SweepSpec {
  const sweep = useStudio((s) => s.sweep);
  const text = useStudio((s) => s.promptListText);
  return useMemo(() => buildSweep({ ...sweep, prompts: parsePromptList(text) }), [sweep, text]);
}

export function useGenerate(resolved: Resolved) {
  const modelId = useStudio((s) => s.modelId);
  const mode = useStudio((s) => s.mode);
  const prompt = useStudio((s) => s.prompt);
  const params = useStudio((s) => s.params);
  const slots = useStudio((s) => s.slots);
  const sweep = useEffectiveSweep();
  const requestParams = resolved.requestParams ?? params;
  const request = useMemo(() => currentRequest({ modelId, mode, prompt, params: requestParams, slots }), [modelId, mode, prompt, requestParams, slots]);
  const auto = useStudio((state) => state.autoImageSizing);
  const requestVersion = useStudio((state) => state.requestVersion);
  const signature = JSON.stringify([request, sweep, auto, requestVersion]);
  const latestSignature = useRef(signature);
  latestSignature.current = signature;
  const generating = useRef(false);
  const submitBusy = useRef(false);
  const active = useRef(true);
  const renderState = useStudio.getState();
  const contextIsActive = useCallback(() => {
    const state = useStudio.getState();
    return active.current && state.page === "studio" &&
      (["modelId", "mode", "prompt", "params", "slots", "sweep", "promptListText", "autoImageSizing", "requestVersion"] as const)
        .every((key) => state[key] === renderState[key]);
  }, [renderState]);
  useEffect(() => {
    active.current = true;
    return () => { active.current = false; latestSignature.current = ""; };
  }, []);
  const conflict = sweepConflict(sweep);
  const blocked = resolved.errors.length > 0 || conflict !== null;
  const hasPrompt = prompt.trim().length > 0 || sweep.prompts.length > 0;
  const estimate = useEstimate(request, sweep, !blocked && hasPrompt);
  const [pending, setPending] = useState<PendingConfirm | null>(null);
  const qc = useQueryClient();
  const { data: models } = useManifests();
  const model = models?.find((m) => m.id === modelId);
  const notConfigured = notConfiguredMessage(model);
  const notConfiguredProvider = notConfigured && model ? providerOf(model) : null;
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { setPending(null); }, [signature]);

  const localCount = countJobs(sweep);
  const canGenerate = !!request && hasPrompt && !blocked && !submitting && !notConfigured;

  const submit = useCallback(
    async (req: GenerationRequest, sw: SweepSpec, confirm: boolean) => {
      if (submitBusy.current || !contextIsActive()) return;
      submitBusy.current = true;
      const submittedSignature = latestSignature.current;
      setSubmitting(true);
      setError(null);
      try {
        const res = await api.createBatch({ request: req, sweep: sw, confirmOverThreshold: confirm });
        useStudio.getState().addBatch({ id: res.batchId, createdAt: Date.now(), jobIds: [], request: req }, res.jobs);
        setPending(null);
      } catch (e) {
        if (e instanceof ApiError && e.confirmRequired && !confirm && submittedSignature === latestSignature.current) {
          const d = (e.details ?? {}) as Partial<EstimateResponse>;
          const est = estimate.data;
          setPending({
            signature: submittedSignature,
            est: {
              jobCount: d.jobCount ?? est?.jobCount ?? countJobs(sw),
              minUsd: d.minUsd ?? est?.minUsd ?? 0,
              maxUsd: d.maxUsd ?? est?.maxUsd ?? 0,
              thresholdUsd: d.thresholdUsd ?? est?.thresholdUsd,
            },
          });
        } else if (e instanceof ApiError && e.kind === "not_configured") {
          // the manifest list was stale: refresh it so the sidebar/Generate reflect reality
          setError(e.message);
          void qc.invalidateQueries({ queryKey: ["manifests"] });
        } else setError((e as Error).message);
      } finally {
        submitBusy.current = false;
        setSubmitting(false);
      }
    },
    [estimate.data, qc, contextIsActive],
  );

  const generate = useCallback(async () => {
    if (!request || !canGenerate || generating.current) return;
    generating.current = true;
    const estimatedSignature = latestSignature.current;
    setError(null);
    try {
      // fresh estimate right before spending money, not a cached one
      const est = await api.estimate({ request, sweep });
      if (!contextIsActive() || estimatedSignature !== latestSignature.current) return;
      if (needsConfirm(est)) {
        setPending({ est, signature: estimatedSignature });
        return;
      }
      await submit(request, sweep, false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      generating.current = false;
    }
  }, [request, sweep, canGenerate, submit, contextIsActive]);

  const confirm = useCallback(() => {
    if (request && canGenerate && pending?.signature === latestSignature.current) void submit(request, sweep, true);
  }, [request, sweep, submit, canGenerate, pending]);

  return { request, sweep, conflict, estimate, localCount, canGenerate, notConfigured, notConfiguredProvider, generate, pending: pending?.signature === signature && !blocked ? pending : null, cancelConfirm: () => setPending(null), confirm, submitting, error };
}
