import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api } from "../api/client";
import { useDebounced, type Resolved } from "../api/hooks";
import type { Manifest } from "../api/types";
import { visibleParams } from "../lib/constraints";
import { buildPayloadPreview, parsePayloadEdit } from "../lib/payload";
import { useEffectiveSweep } from "./useGenerate";
import { currentRequest, useStudio } from "../store/studio";

export function RawRequestTab({ manifest, resolved }: { manifest: Manifest; resolved: Resolved }) {
  const mode = useStudio((s) => s.mode);
  const prompt = useStudio((s) => s.prompt);
  const params = useStudio((s) => s.params);
  const setPrompt = useStudio((s) => s.setPrompt);
  const replaceParams = useStudio((s) => s.replaceParams);
  const slots = useStudio((s) => s.slots);
  const sweep = useEffectiveSweep();
  const [draft, setDraft] = useState<{ text: string; signature: string } | null>(null);
  const [idx, setIdx] = useState(0);

  // Real payload from the backend adapter's build_payload (single job, no sweep).
  const current = currentRequest({ modelId: manifest.id, mode, prompt, params: resolved.requestParams ?? params, slots });
  const signature = JSON.stringify({ request: current, sweep });
  const debouncedSignature = useDebounced(signature, 300);
  const request = useMemo(() => JSON.parse(debouncedSignature) as { request: NonNullable<typeof current>; sweep: typeof sweep }, [debouncedSignature]);
  const fresh = signature === debouncedSignature && resolved.errors.length === 0;
  const edit = draft?.signature === signature ? draft.text : null;
  const setEdit = (text: string | null) => setDraft(text === null ? null : { text, signature });
  const remote = useQuery({
    queryKey: ["payload", debouncedSignature],
    queryFn: () => api.payload(request),
    enabled: fresh && !!current && (prompt.trim().length > 0 || sweep.prompts.length > 0),
    retry: false,
  });
  const payloads = fresh ? remote.data?.payloads ?? [] : [];
  const cur = payloads[Math.min(idx, Math.max(0, payloads.length - 1))];
  const remotePayload = cur?.payload ?? (resolved.errors.length === 0 ? resolved.payload : undefined);
  const fromBackend = fresh && remotePayload !== undefined && !remote.isError;
  const generated = useMemo(
    () => JSON.stringify(fromBackend ? remotePayload : buildPayloadPreview(manifest, mode, prompt, resolved.effective), null, 2),
    [fromBackend, remotePayload, manifest, mode, prompt, resolved.effective],
  );
  const parsed = useMemo(() => (edit === null ? null : parsePayloadEdit(manifest, mode, edit, !fromBackend)), [edit, manifest, mode, fromBackend]);

  function apply() {
    if (!parsed?.ok || draft?.signature !== signature) return;
    const noPath = new Set(visibleParams(manifest, mode).filter((p) => !p.providerPath).map((p) => p.key));
    const kept = Object.fromEntries(Object.entries(params).filter(([k]) => noPath.has(k)));
    replaceParams({ ...kept, ...parsed.params });
    useStudio.getState().setAutoImageSizing(false);
    if (parsed.prompt !== undefined) setPrompt(parsed.prompt);
    setEdit(null);
  }

  return (
    <div className="raw">
      <p className="field-note">
        {fromBackend
          ? "Payload thật do backend dựng (build_payload; base64 ảnh được che)."
          : `Bản xem trước dựng từ providerPath trong manifest${remote.error ? ` (backend: ${(remote.error as Error).message})` : ""}.`} Sửa JSON rồi
        “Áp dụng” để cập nhật form; backend vẫn validate lại toàn bộ.
      </p>
      {payloads.length > 1 && (
        <div className="row">
          <label htmlFor="raw-job" className="field-note">
            Job
          </label>
          <select id="raw-job" value={Math.min(idx, payloads.length - 1)} onChange={(e) => (setIdx(Number(e.target.value)), setEdit(null))}>
            {payloads.map((p, i) => (
              <option key={p.jobId} value={i}>
                #{i + 1}/{payloads.length}
                {p.variantCount && p.variantCount > 1 ? ` (${p.variantCount} bản native)` : ""}
              </option>
            ))}
          </select>
        </div>
      )}
      <textarea className="mono" rows={18} spellCheck={false} value={edit ?? generated} onChange={(e) => setEdit(e.target.value)} aria-label="Request thô (JSON)" />
      {parsed && (
        <>
          {parsed.warnings.length > 0 && (
            <ul className="warn-text">
              {parsed.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          )}
          {parsed.errors.length > 0 ? (
            <ul className="errors" role="alert">
              {parsed.errors.map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          ) : (
            <p className="ok-text">JSON hợp lệ theo manifest.</p>
          )}
          <div className="row end">
            <button className="btn sm" onClick={() => setEdit(null)}>
              Hoàn tác
            </button>
            <button className="btn sm primary" disabled={!parsed.ok} onClick={apply}>
              Áp dụng vào form
            </button>
          </div>
        </>
      )}
    </div>
  );
}
