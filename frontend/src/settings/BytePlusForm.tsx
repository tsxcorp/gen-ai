import { useEffect, useState } from "react";
import type { BytePlusProviderView } from "../api/types";
import { buildBytePlusPayload, PROVIDER_TITLE } from "../lib/providers";
import { ProviderShell } from "./ProviderShell";
import { useProviderMutations } from "./useProviderMutations";

export function BytePlusForm({ view }: { view?: BytePlusProviderView }) {
  const [apiKey, setApiKey] = useState("");
  const [region, setRegion] = useState("");
  useEffect(() => setRegion(view?.region ?? ""), [view?.region]);
  const m = useProviderMutations(
    "byteplus",
    () => buildBytePlusPayload({ apiKey, region }),
    () => setApiKey(""),
    () => {
      setApiKey("");
      setRegion("");
    },
  );
  const hasKey = !!view?.hasKey;
  return (
    <ProviderShell title={PROVIDER_TITLE.byteplus} configured={!!(view?.configured ?? view?.hasKey)} canSave={apiKey.trim() !== "" || hasKey} {...m}>
      <div className="field">
        <label className="field-label" htmlFor="bp-key">
          API key <span className={`badge ${hasKey ? "ok" : "stale"}`}>{hasKey ? "đã lưu key" : "chưa có key"}</span>
        </label>
        <input
          id="bp-key"
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={hasKey ? "Để trống để giữ key hiện tại" : "API key BytePlus ModelArk"}
        />
      </div>
      <div className="field">
        <label className="field-label" htmlFor="bp-region">
          Region
        </label>
        <input id="bp-region" value={region} onChange={(e) => setRegion(e.target.value)} placeholder="ap-southeast (mặc định)" />
      </div>
      <p className="field-note">URL video kết quả chỉ sống 24 giờ nên được tải về ngay. Tài khoản cá nhân chạy tối đa 3 job đồng thời.</p>
    </ProviderShell>
  );
}
