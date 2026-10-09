import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { PromptLibrary } from "../prompts/PromptLibrary";
import { useStudio } from "../store/studio";

export function PromptField() {
  const prompt = useStudio((s) => s.prompt);
  const setPrompt = useStudio((s) => s.setPrompt);
  const modelId = useStudio((s) => s.modelId);
  const [suggestion, setSuggestion] = useState<string | null>(null);
  const enhance = useMutation({
    mutationFn: () => api.enhance(modelId as string, prompt),
    onSuccess: (r) => setSuggestion(r.suggestion),
  });

  return (
    <div className="field">
      <div className="field-label between">
        <label htmlFor="f-prompt">Prompt</label>
        <span className="row">
          <PromptLibrary />
          <button
            type="button"
            className="btn ghost sm"
            disabled={!modelId || !prompt.trim() || enhance.isPending}
            onClick={() => enhance.mutate()}
            title="Gemini viết lại prompt; bạn duyệt trước khi dùng"
          >
            {enhance.isPending ? "Đang cải thiện…" : "✨ Enhance"}
          </button>
        </span>
      </div>
      <textarea id="f-prompt" rows={5} value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Mô tả cảnh bạn muốn tạo…  (Ctrl/Cmd+Enter để Generate)" />
      {enhance.error && <p className="error">{(enhance.error as Error).message}</p>}
      {suggestion !== null && (
        <div className="suggestion">
          <div className="field-label">Gợi ý từ Enhance (sửa được)</div>
          <textarea rows={5} value={suggestion} onChange={(e) => setSuggestion(e.target.value)} />
          <div className="row end">
            <button
              className="btn sm primary"
              onClick={() => {
                setPrompt(suggestion);
                setSuggestion(null);
              }}
            >
              Chấp nhận
            </button>
            <button className="btn sm" onClick={() => setSuggestion(null)}>
              Bỏ
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
