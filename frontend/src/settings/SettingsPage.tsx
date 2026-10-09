import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ProviderId } from "../api/types";
import { PROVIDER_IDS, PROVIDER_LABEL } from "../lib/providers";
import { useStudio } from "../store/studio";
import { BytePlusForm } from "./BytePlusForm";
import { OpenAIForm } from "./OpenAIForm";
import { VertexForm } from "./VertexForm";

const isOn = (v?: { configured?: boolean; hasKey?: boolean }) => !!(v?.configured ?? v?.hasKey);

export function SettingsPage() {
  const { data, error, isLoading } = useQuery({ queryKey: ["providers"], queryFn: api.providers });
  const tab = useStudio((s) => s.settingsProvider);
  const setTab = useStudio((s) => s.setSettingsProvider);
  const configured: Record<ProviderId, boolean> = { vertex: isOn(data?.vertex), openai: isOn(data?.openai), byteplus: isOn(data?.byteplus) };
  return (
    <div className="settings">
      <h1>Cài đặt provider</h1>
      <div className="seg tabs" role="tablist" aria-label="Provider">
        {PROVIDER_IDS.map((p) => (
          <button key={p} role="tab" aria-selected={tab === p} className={tab === p ? "on" : ""} onClick={() => setTab(p)}>
            {PROVIDER_LABEL[p]} <span className={`dot ${configured[p] ? "ok" : "off"}`} aria-label={configured[p] ? "đã cấu hình" : "chưa cấu hình"} />
          </button>
        ))}
      </div>
      {isLoading && <p className="muted">Đang tải…</p>}
      {error && <p className="error">{(error as Error).message}</p>}
      {/* key={tab}: switching provider never carries typed values over */}
      {tab === "vertex" && <VertexForm key="vertex" view={data?.vertex} />}
      {tab === "openai" && <OpenAIForm key="openai" view={data?.openai} />}
      {tab === "byteplus" && <BytePlusForm key="byteplus" view={data?.byteplus} />}
    </div>
  );
}
