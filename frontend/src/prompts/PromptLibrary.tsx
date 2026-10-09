import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import type { PromptTemplate } from "../api/types";
import { newId } from "../lib/id";
import { useStudio } from "../store/studio";

export function PromptLibrary() {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const qc = useQueryClient();
  const prompt = useStudio((s) => s.prompt);
  const setPrompt = useStudio((s) => s.setPrompt);
  // Invariant 24: per-item writes, never before the list has loaded successfully.
  const { data = [], error, isSuccess, refetch } = useQuery({ queryKey: ["prompts"], queryFn: api.prompts, enabled: open });
  const done = { onSuccess: () => qc.invalidateQueries({ queryKey: ["prompts"] }) };
  const save = useMutation({ mutationFn: (p: PromptTemplate) => api.upsertPrompt(p), ...done });
  const remove = useMutation({ mutationFn: (id: string) => api.deletePrompt(id), ...done });

  function add() {
    if (!isSuccess || !prompt.trim() || !name.trim()) return;
    save.mutate({ id: newId(), name: name.trim(), text: prompt });
    setName("");
  }

  return (
    <div className="popwrap">
      <button type="button" className="btn ghost sm" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        Thư viện prompt
      </button>
      {open && (
        <div className="popover" role="dialog" aria-label="Thư viện prompt">
          {error && (
            <>
              <p className="error">{(error as Error).message}</p>
              <button className="btn sm" onClick={() => void refetch()}>
                Tải lại danh sách
              </button>
            </>
          )}
          <ul className="list">
            {!isSuccess && !error && <li className="muted">Đang tải…</li>}
            {isSuccess && data.length === 0 && <li className="muted">Chưa có prompt nào</li>}
            {data.map((p) => (
              <li key={p.id}>
                <button
                  className="link"
                  title={p.text}
                  onClick={() => {
                    setPrompt(prompt.trim() ? `${prompt}\n${p.text}` : p.text);
                    setOpen(false);
                  }}
                >
                  {p.name}
                </button>
                <button className="btn ghost sm" aria-label={`Xóa ${p.name}`} disabled={remove.isPending} onClick={() => remove.mutate(p.id)}>
                  ✕
                </button>
              </li>
            ))}
          </ul>
          <div className="row">
            <input placeholder="Tên để lưu prompt hiện tại" value={name} onChange={(e) => setName(e.target.value)} />
            <button className="btn sm" disabled={!isSuccess || !prompt.trim() || !name.trim() || save.isPending} onClick={add}>
              Lưu
            </button>
          </div>
          {(save.error || remove.error) && <p className="error">{((save.error ?? remove.error) as Error).message}</p>}
        </div>
      )}
    </div>
  );
}
