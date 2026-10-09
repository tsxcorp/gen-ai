import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { manifestKey } from "../api/hooks";
import type { Params, Preset } from "../api/types";
import { newId } from "../lib/id";
import { currentRequest, useStudio } from "../store/studio";

export function PresetsMenu({ params, disabled = false }: { params?: Params; disabled?: boolean }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const qc = useQueryClient();
  // Invariant 24: writes are per item and only possible once the list has loaded successfully.
  const { data = [], error, isSuccess, refetch } = useQuery({ queryKey: ["presets"], queryFn: api.presets, enabled: open });
  const done = { onSuccess: () => qc.invalidateQueries({ queryKey: ["presets"] }) };
  const save = useMutation({ mutationFn: (p: Preset) => api.upsertPreset(p), ...done });
  const remove = useMutation({ mutationFn: (id: string) => api.deletePreset(id), ...done });

  function add() {
    const s = useStudio.getState();
    const req = currentRequest({ ...s, params: params ?? s.params });
    if (!req || !name.trim()) return;
    if (!isSuccess || disabled) return;
    save.mutate({ id: newId(), name: name.trim(), modelId: req.modelId, mode: req.mode, params: req.params, prompt: req.prompt || undefined, createdAt: new Date().toISOString() });
    setName("");
  }

  async function load(p: Preset) {
    try {
      setErr(null);
      const m = await qc.fetchQuery({ queryKey: manifestKey(p.modelId), queryFn: () => api.manifest(p.modelId), staleTime: 60_000 });
      useStudio.getState().loadRequest(m, { mode: p.mode, params: p.params, prompt: p.prompt });
      setOpen(false);
    } catch (e) {
      setErr(`Không nạp được preset: ${(e as Error).message}`);
    }
  }

  const hasModel = useStudio((s) => s.modelId !== null);
  return (
    <div className="popwrap">
      <button type="button" className="btn ghost sm" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        Preset
      </button>
      {open && (
        <div className="popover" role="dialog" aria-label="Preset">
          {(error || err) && <p className="error">{err ?? (error as Error).message}</p>}
          {error && (
            <button className="btn sm" onClick={() => void refetch()}>
              Tải lại danh sách
            </button>
          )}
          <ul className="list">
            {!isSuccess && !error && <li className="muted">Đang tải…</li>}
            {isSuccess && data.length === 0 && <li className="muted">Chưa có preset nào</li>}
            {data.map((p) => (
              <li key={p.id}>
                <button className="link" onClick={() => void load(p)} title={`${p.modelId} · ${p.mode}`}>
                  {p.name} <span className="muted">· {p.modelId}</span>
                </button>
                <button className="btn ghost sm" aria-label={`Xóa ${p.name}`} disabled={remove.isPending} onClick={() => remove.mutate(p.id)}>
                  ✕
                </button>
              </li>
            ))}
          </ul>
          <div className="row">
            <input placeholder="Tên preset (lưu tham số hiện tại)" value={name} onChange={(e) => setName(e.target.value)} />
            <button className="btn sm" disabled={disabled || !isSuccess || !hasModel || !name.trim() || save.isPending} onClick={add}>
              Lưu
            </button>
          </div>
          {(save.error || remove.error) && <p className="error">{((save.error ?? remove.error) as Error).message}</p>}
        </div>
      )}
    </div>
  );
}
