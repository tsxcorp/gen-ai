import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, assetUrl } from "../api/client";
import { saveBlob } from "../lib/download";
import { useManifests } from "../api/hooks";
import type { Job } from "../api/types";
import { jobPrompt } from "../lib/job";
import { useStudio } from "../store/studio";
import { AssetView, extOf, jobWarnings } from "./AssetView";
import { makeVideo, reuseJob } from "./actions";
import { ProviderTag } from "./ProviderTag";

const STATUS_LABEL: Record<Job["status"], string> = {
  queued: "Đang chờ",
  running: "Đang chạy",
  succeeded: "Xong",
  failed: "Lỗi",
  blocked: "Bị chặn",
  canceled: "Đã hủy",
};

function paramSummary(j: Job): string {
  return Object.entries(j.effectiveParams)
    .filter(([, v]) => v !== null && v !== "" && typeof v !== "object")
    .map(([k, v]) => `${k}=${String(v)}`)
    .join(" · ");
}

export function ResultCell({ job }: { job: Job }) {
  const qc = useQueryClient();
  const { data: models = [] } = useManifests();
  const selected = useStudio((s) => s.selected.includes(job.id));
  const toggle = useStudio((s) => s.toggleSelect);
  const markDownloaded = useStudio((s) => s.markDownloaded);
  const upsert = useStudio((s) => s.upsertJob);
  const batch = useStudio((s) => s.batches.find((b) => b.id === job.batchId));
  const [msg, setMsg] = useState<string | null>(null);
  const [menu, setMenu] = useState(false);
  const downloaded = useStudio((s) => s.downloaded);
  const assets = job.assets;
  const multi = assets.length > 1;
  const asset = assets[0];
  const isImage = asset?.mime.startsWith("image/");
  const warnings = jobWarnings(job);
  const pct = Math.round((job.progress ?? 0) * 100);

  async function retry() {
    setMsg(null);
    try {
      upsert(await api.retryJob(job.id));
    } catch (e) {
      setMsg((e as Error).message);
    }
  }
  async function zipJob() {
    const ids = assets.map((a) => a.id);
    saveBlob(await api.zip(ids), `${job.id.slice(0, 8)}.zip`);
    markDownloaded(ids);
  }
  const guard = (p: Promise<unknown>) => p.catch((e) => setMsg((e as Error).message));

  return (
    <figure className={`cell ${job.status}${selected ? " selected" : ""}${multi ? " multi" : ""}`}>
      <div className={`media${multi ? " multi" : ""}`}>
        {job.status === "succeeded" && asset ? (
          multi ? (
            assets.map((a, i) => (
              <div key={a.id} className="asset" data-testid="job-asset">
                <AssetView asset={a} alt={`${jobPrompt(job).slice(0, 60)} (#${i + 1})`} />
                <span className="asset-tag">
                  #{i + 1}
                  {downloaded[a.id] ? " ✓" : ""}
                </span>
              </div>
            ))
          ) : (
            <AssetView asset={asset} alt={jobPrompt(job).slice(0, 80)} />
          )
        ) : (
          <div className="placeholder">
            <span className={`status-dot ${job.status}`} />
            <div>{STATUS_LABEL[job.status]}</div>
            {job.status === "running" && (
              <div className="progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
                <div style={{ width: job.progress !== undefined ? `${pct}%` : "40%" }} className={job.progress === undefined ? "indet" : ""} />
              </div>
            )}
            {job.error && (
              <div className="job-error">
                <strong>{job.error.kind}</strong>: {job.error.message}
              </div>
            )}
            {job.status === "canceled" && job.bestEffortCancel && <div className="muted">best-effort</div>}
          </div>
        )}
        {job.status === "succeeded" && (
          <label className="pick" title="Chọn">
            <input type="checkbox" checked={selected} onChange={() => toggle(job.id)} aria-label="Chọn kết quả" />
          </label>
        )}
      </div>
      <figcaption>
        <ProviderTag job={job} />
        <div className="cap-prompt" title={jobPrompt(job)}>
          {jobPrompt(job) || "—"}
        </div>
        <div className="cap-params" title={paramSummary(job)}>
          {paramSummary(job)}
        </div>
        <div className="cell-actions">
          {(job.status === "failed" || job.status === "blocked" || job.status === "canceled") && (
            <button className="btn sm" onClick={() => void retry()} title={job.status === "blocked" ? "Không tự retry job bị chặn; retry tay vẫn được" : undefined}>
              {job.status === "blocked" ? "Thử lại (tay)" : "Retry"}
            </button>
          )}
          <button className="btn ghost sm" onClick={() => void guard(reuseJob(qc, job, batch))} title="Nạp tham số vào panel để sửa và chạy lại">
            Reuse / Vary
          </button>
          {job.status === "succeeded" && asset && (
            <>
              {assets.map((a, i) => (
                // invariant 16: mark ONLY the asset that was actually downloaded
                <a key={a.id} className="btn ghost sm" href={assetUrl(a.id)} download={`${job.id.slice(0, 8)}-${i + 1}.${extOf(a.mime)}`} onClick={() => markDownloaded([a.id])}>
                  {multi ? `Tải #${i + 1}` : "Tải"}
                </a>
              ))}
              {multi && (
                <button className="btn ghost sm" onClick={() => void guard(zipJob())} title="Tải cả nhóm thành một file .zip">
                  Tải nhóm .zip
                </button>
              )}
              {isImage && (
                <span className="popwrap">
                  <button className="btn ghost sm" onClick={() => setMenu((o) => !o)}>
                    Làm video ▾
                  </button>
                  {menu && (
                    <div className="popover small">
                      {(["first_frame", "last_frame"] as const).map((slot) => (
                        <button
                          key={slot}
                          className="link"
                          onClick={() => {
                            setMenu(false);
                            void makeVideo(qc, models, job, asset, slot).then((e) => setMsg(e));
                          }}
                        >
                          {slot === "first_frame" ? "Làm frame đầu" : "Làm frame cuối"}
                        </button>
                      ))}
                    </div>
                  )}
                </span>
              )}
            </>
          )}
        </div>
        {warnings.map((w, i) => (
          <div key={`${i}:${w}`} className="warn-text" role="status">
            {w}
          </div>
        ))}
        {msg && <div className="error">{msg}</div>}
      </figcaption>
    </figure>
  );
}
