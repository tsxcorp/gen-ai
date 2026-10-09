import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { manifestKey, useManifests } from "../api/hooks";
import { modelWarnings } from "../lib/manifestMeta";
import { groupModels, KIND_LABEL, PROVIDER_LABEL, providersWithModels, type ProviderFilter } from "../lib/providers";
import { useStudio } from "../store/studio";
import { StatusBadge } from "../ui/Badge";

export function ModelSidebar() {
  const { data, isLoading, error } = useManifests();
  const modelId = useStudio((s) => s.modelId);
  const selectModel = useStudio((s) => s.selectModel);
  const qc = useQueryClient();
  const openSettings = useStudio((s) => s.openSettings);
  const [err, setErr] = useState<string | null>(null);
  const [filter, setFilter] = useState<ProviderFilter>("all");
  const models = data ?? [];
  const present = providersWithModels(models);
  const groups = groupModels(models, filter);

  async function pick(id: string) {
    try {
      setErr(null);
      const m = await qc.fetchQuery({ queryKey: manifestKey(id), queryFn: () => api.manifest(id), staleTime: 60_000 });
      selectModel(m);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <aside className="sidebar" aria-label="Chọn model">
      <h2>Model</h2>
      {isLoading && <p className="muted pad">Đang tải…</p>}
      {error && <p className="error pad">Không tải được danh sách model: {(error as Error).message}</p>}
      {err && <p className="error pad">{err}</p>}
      {present.length > 1 && (
        <div className="chips" role="group" aria-label="Lọc theo provider">
          {(["all", ...present] as ProviderFilter[]).map((f) => (
            <button key={f} type="button" className={`chip${filter === f ? " on" : ""}`} aria-pressed={filter === f} onClick={() => setFilter(f)}>
              {f === "all" ? "Tất cả" : PROVIDER_LABEL[f]}
            </button>
          ))}
        </div>
      )}
      {groups.map((g) => (
        <div key={g.provider} className={`prov-group${g.configured ? "" : " unconfigured"}`} data-testid={`prov-${g.provider}`}>
          <div className="prov-head">
            <span className={`badge prov ${g.provider}`}>{PROVIDER_LABEL[g.provider]}</span>
            {!g.configured && (
              <button className="link" onClick={() => openSettings(g.provider)} title={`Nhập thông tin xác thực ${PROVIDER_LABEL[g.provider]}`}>
                Cài đặt
              </button>
            )}
          </div>
          {g.kinds.map((k) => (
            <div key={k.kind} className="model-group">
              <div className="group-title">{KIND_LABEL[k.kind]}</div>
              {k.models.map((m) => {
                const warns = modelWarnings(m);
                return (
                  <button
                    key={m.id}
                    className={`model-item${m.id === modelId ? " active" : ""}${g.configured ? "" : " dim"}`}
                    onClick={() => void pick(m.id)}
                    title={[!g.configured ? `Chưa cấu hình ${PROVIDER_LABEL[g.provider]}` : "", ...warns.map((w) => w.text)].filter(Boolean).join("\n") || m.id}
                  >
                    <span className="model-name">{m.label ?? m.id}</span>
                    <span className="model-badges">
                      <StatusBadge status={m.status} />
                      {warns.length > 0 && (
                        <span className={`badge ${warns.some((w) => w.level === "danger") ? "deprecated" : "stale"}`} aria-label="Cảnh báo">
                          ⚠
                        </span>
                      )}
                    </span>
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      ))}
    </aside>
  );
}
