import { useEffect, useState } from "react";
import type { OpenAIProviderView } from "../api/types";
import { buildOpenAIPayload, PROVIDER_TITLE } from "../lib/providers";
import { ProviderShell } from "./ProviderShell";
import { useProviderMutations } from "./useProviderMutations";

export function OpenAIForm({ view }: { view?: OpenAIProviderView }) {
  const [apiKey, setApiKey] = useState("");
  const [organization, setOrganization] = useState("");
  const [project, setProject] = useState("");
  useEffect(() => {
    setOrganization(view?.organization ?? "");
    setProject(view?.project ?? "");
  }, [view?.organization, view?.project]);
  const m = useProviderMutations(
    "openai",
    () => buildOpenAIPayload({ apiKey, organization, project }),
    () => setApiKey(""),
    () => {
      setApiKey("");
      setOrganization("");
      setProject("");
    },
  );
  const hasKey = !!view?.hasKey;
  return (
    <ProviderShell title={PROVIDER_TITLE.openai} configured={!!(view?.configured ?? view?.hasKey)} canSave={apiKey.trim() !== "" || hasKey} {...m}>
      <div className="field">
        <label className="field-label" htmlFor="oa-key">
          API key <span className={`badge ${hasKey ? "ok" : "stale"}`}>{hasKey ? "đã lưu key" : "chưa có key"}</span>
        </label>
        <input
          id="oa-key"
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={hasKey ? "Để trống để giữ key hiện tại" : "sk-…"}
        />
      </div>
      <div className="field">
        <label className="field-label" htmlFor="oa-org">
          Organization (tùy chọn)
        </label>
        <input id="oa-org" value={organization} onChange={(e) => setOrganization(e.target.value)} placeholder="org-…" />
      </div>
      <div className="field">
        <label className="field-label" htmlFor="oa-proj">
          Project (tùy chọn)
        </label>
        <input id="oa-proj" value={project} onChange={(e) => setProject(e.target.value)} placeholder="proj_…" />
      </div>
      <p className="field-note">gpt-image có thể cần Org Verification [?] trên tài khoản OpenAI.</p>
    </ProviderShell>
  );
}
