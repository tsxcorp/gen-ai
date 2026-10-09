import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { VertexAuthMethod, VertexProviderView } from "../api/types";
import { buildVertexPayload, PROVIDER_TITLE, type VertexForm as VertexFormState } from "../lib/providers";
import { ProviderShell } from "./ProviderShell";
import { useProviderMutations } from "./useProviderMutations";
import { FileDropzone, validateFiles } from "../ui/FileDropzone";

export function VertexForm({ view }: { view?: VertexProviderView }) {
  const [authMethod, setAuthMethod] = useState<VertexAuthMethod>("service_account");
  const [projectId, setProjectId] = useState("");
  const [location, setLocation] = useState("");
  const [gcsBucket, setGcsBucket] = useState("");
  const [source, setSource] = useState<VertexFormState["source"]>("file");
  const [fileInfo, setFileInfo] = useState<{ name: string } | null>(null);
  const [fileProblem, setFileProblem] = useState<string | null>(null);
  const fileRead = useRef(0);
  const [reading, setReading] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [path, setPath] = useState("");
  const [json, setJson] = useState("");

  useLayoutEffect(() => () => { fileRead.current += 1; }, []);
  useLayoutEffect(() => {
    fileRead.current += 1;
    setReading(false);
    setJson("");
    setFileInfo(null);
    setFileProblem(null);
    setSelectedFiles([]);
  }, [source, authMethod]);

  useEffect(() => {
    if (!view) return;
    if (view.authMethod) setAuthMethod(view.authMethod);
    setProjectId(view.projectId ?? "");
    setLocation(view.location ?? "");
    setGcsBucket(view.gcsBucket ?? "");
    setPath(view.serviceAccountPath ?? "");
  }, [view]);

  const clearKey = () => {
    fileRead.current += 1;
    setReading(false);
    setJson("");
    setFileInfo(null);
    setFileProblem(null);
    setSelectedFiles([]);
  };
  const m = useProviderMutations(
    "vertex",
    () => buildVertexPayload({ authMethod, projectId, location, gcsBucket, source, path, json }),
    clearKey,
    () => {
      clearKey();
      setProjectId("");
      setLocation("");
      setGcsBucket("");
      setPath("");
    },
  );

  let jsonProblem: string | null = null;
  if (source === "json" && json.trim()) {
    if (new Blob([json]).size > 1024 * 1024) jsonProblem = "JSON service account vượt giới hạn 1 MB";
    else {
      try {
        JSON.parse(json);
      } catch {
        jsonProblem = "JSON service account không hợp lệ";
      }
    }
  }
  async function onPickFile(f: File | undefined) {
    const token = ++fileRead.current;
    setFileProblem(null);
    setFileInfo(null);
    setJson("");
    if (!f) return;
    const problem = validateFiles([f], "application/json,.json", 1024 * 1024, 1);
    if (problem) { setFileProblem(problem); return; }
    setSelectedFiles([f]);
    setReading(true);
    try {
      const text = await f.text();
      if (token !== fileRead.current) return;
      const parsed: unknown = JSON.parse(text);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        setFileProblem("Đây không phải file service account JSON của Google Cloud.");
        return;
      }
      const obj = parsed as Record<string, unknown>;
      if ("installed" in obj || "web" in obj) {
        setFileProblem(
          "Đây là file OAuth client (client_secret), không phải service account key. Tạo key ở Google Cloud Console → IAM & Admin → Service Accounts → Keys → Add key → JSON.",
        );
        return;
      }
      if (obj.type !== "service_account" || typeof obj.private_key !== "string" || !obj.private_key.trim() || typeof obj.client_email !== "string" || !obj.client_email.trim()) {
        setFileProblem("Đây không phải file service account JSON của Google Cloud.");
        return;
      }
      setJson(text);
      setFileInfo({ name: f.name });
      if (typeof obj.project_id === "string") setProjectId(obj.project_id);
      if (!location.trim()) setLocation("global");
    } catch {
      if (token === fileRead.current) setFileProblem("Không đọc được file: không phải JSON hợp lệ.");
    } finally {
      if (token === fileRead.current) setReading(false);
    }
  }

  const sa = authMethod === "service_account";
  const hasNewKey = source === "path" ? path.trim() !== "" : json.trim() !== "";
  const hasStoredKey = !!view?.hasKey && view.authMethod !== "adc";
  const canSave =
    !reading && projectId.trim() !== "" && location.trim() !== "" && (!sa || (!jsonProblem && !fileProblem && (hasNewKey || hasStoredKey)));

  return (
    <ProviderShell title={PROVIDER_TITLE.vertex} configured={!!(view?.configured ?? view?.hasKey)} canSave={canSave} {...m}>
      <div className="field">
        <div className="field-label">Xác thực</div>
        <div className="seg" role="group" aria-label="Phương thức xác thực Vertex">
          <button type="button" className={sa ? "on" : ""} onClick={() => setAuthMethod("service_account")}>
            Service account
          </button>
          <button type="button" className={!sa ? "on" : ""} onClick={() => setAuthMethod("adc")}>
            ADC (gcloud)
          </button>
        </div>
      </div>
      <div className="field">
        <label className="field-label" htmlFor="s-project">
          Project ID
        </label>
        <input id="s-project" value={projectId} onChange={(e) => setProjectId(e.target.value)} />
      </div>
      <div className="field">
        <label className="field-label" htmlFor="s-loc">
          Location
        </label>
        <input id="s-loc" value={location} onChange={(e) => setLocation(e.target.value)} placeholder="us-central1 / global" />
      </div>
      {sa ? (
        <div className="field">
          <div className="field-label">
            Service account <span className={`badge ${hasStoredKey ? "ok" : "stale"}`}>{hasStoredKey ? "đã lưu key" : "chưa có key"}</span>
          </div>
          <div className="seg">
            <button type="button" className={source === "file" ? "on" : ""} onClick={() => setSource("file")}>
              Nhập file JSON
            </button>
            <button type="button" className={source === "path" ? "on" : ""} onClick={() => setSource("path")}>
              Đường dẫn file
            </button>
            <button type="button" className={source === "json" ? "on" : ""} onClick={() => setSource("json")}>
              Dán JSON
            </button>
          </div>
          {source === "file" ? (
            <div>
              <FileDropzone accept="application/json,.json" maxBytes={1024 * 1024} maxFiles={1}
                label="Chọn file service account JSON" hint="Kéo thả hoặc chọn JSON · tối đa 1 MB · không hiển thị nội dung key"
                selectedFiles={selectedFiles} busy={reading} disabled={m.save.isPending || m.remove.isPending}
                onFiles={(files) => void onPickFile(files[0])} />
              {fileInfo && (
                <p className="ok-text">
                  Đã xác thực file {fileInfo.name}. Bấm Lưu để ghi vào backend.
                </p>
              )}
              {fileProblem && <p className="error" role="alert">{fileProblem}</p>}
              {!fileInfo && hasStoredKey && <p className="field-note">Đã có key. Chọn file mới chỉ khi muốn thay.</p>}
            </div>
          ) : source === "path" ? (
            <input aria-label="Đường dẫn service account" value={path} onChange={(e) => setPath(e.target.value)} placeholder="/đường/dẫn/service-account.json" />
          ) : (
            <textarea
              aria-label="Service account JSON"
              rows={6}
              className="mono"
              value={json}
              onChange={(e) => setJson(e.target.value)}
              placeholder={hasStoredKey ? "Để trống để giữ key hiện tại" : '{"type":"service_account", ...}'}
              autoComplete="off"
              spellCheck={false}
            />
          )}
          {jsonProblem && <p className="error">{jsonProblem}</p>}
        </div>
      ) : (
        <p className="field-note">
          ADC dùng thông tin đăng nhập có sẵn trên máy chạy backend: <code>gcloud auth application-default login</code> (có thể thêm{" "}
          <code>--client-id-file</code>). Không cần nhập key ở đây.
        </p>
      )}
      <div className="field">
        <label className="field-label" htmlFor="s-gcs">
          GCS bucket (tùy chọn)
        </label>
        <input id="s-gcs" value={gcsBucket} onChange={(e) => setGcsBucket(e.target.value)} placeholder="my-bucket" />
      </div>
    </ProviderShell>
  );
}
