import { useState } from "react";
import { api } from "../api/client";
import { saveBlob } from "../lib/download";
import { isActive } from "../lib/job";
import { unsavedAssetIds, useStudio } from "../store/studio";
import { ResultCell } from "./ResultCell";
import { Icon } from "../ui/Icon";

export function ResultsGrid() {
  const batches = useStudio((s) => s.batches);
  const jobs = useStudio((s) => s.jobs);
  const selected = useStudio((s) => s.selected);
  const downloaded = useStudio((s) => s.downloaded);
  const clearSel = useStudio((s) => s.clearSelection);
  const markDownloaded = useStudio((s) => s.markDownloaded);
  const setCompare = useStudio((s) => s.setCompare);
  const sse = useStudio((s) => s.sseConnected);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const unsaved = unsavedAssetIds(jobs, downloaded);
  const selectedAssets = selected.flatMap((id) => jobs[id]?.assets.map((a) => a.id) ?? []);

  async function zip(ids: string[], name: string) {
    setBusy(true);
    setErr(null);
    try {
      saveBlob(await api.zip(ids), name);
      markDownloaded(ids);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function cancel(batchId: string) {
    try {
      await api.cancelBatch(batchId);
      const b = await api.batch(batchId);
      b.jobs.forEach((j) => useStudio.getState().upsertJob(j));
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <main className="results">
      <div className="banner warn persistent">
        Kết quả mất khi reload, hãy tải về.
        {unsaved.length > 0 && (
          <button className="btn sm primary" disabled={busy} onClick={() => void zip(unsaved, "ai-gen-studio-all.zip")}>
            Tải tất cả chưa lưu ({unsaved.length}) .zip
          </button>
        )}
        {!sse && <span className="muted"> · SSE chưa kết nối, đang đồng bộ định kỳ</span>}
      </div>
      <div className="toolbar">
        <span>{selected.length > 0 ? `Đã chọn ${selected.length}` : "Chọn kết quả để tải ZIP hoặc so sánh"}</span>
        <button className="btn sm" disabled={selectedAssets.length === 0 || busy} onClick={() => void zip(selectedAssets, "ai-gen-studio.zip")}>
          Tải ZIP
        </button>
        <button className="btn sm" disabled={selected.length < 2 || selected.length > 4} onClick={() => setCompare(true)} title="Chọn 2–4 kết quả">
          So sánh
        </button>
        <button className="btn ghost sm" disabled={selected.length === 0} onClick={clearSel}>
          Bỏ chọn
        </button>
        {err && <span className="error">{err}</span>}
      </div>
      {batches.length === 0 && <div className="empty-results muted"><Icon name="image" /><strong>Không gian cho ý tưởng của bạn</strong><p>Chọn model, nhập mô tả rồi nhấn Generate.</p><span>Muốn sửa ảnh? Chọn Sửa ảnh và thêm ảnh gốc.</span><kbd>Ctrl / Cmd + Enter</kbd></div>}
      {batches.map((b) => {
        const js = b.jobIds.map((id) => jobs[id]).filter((j): j is NonNullable<typeof j> => !!j);
        const active = js.filter((j) => isActive(j.status)).length;
        const done = js.filter((j) => j.status === "succeeded").length;
        return (
          <section key={b.id} className="batch">
            <div className="batch-head">
              <span>
                Batch <code>{b.id.slice(0, 8)}</code> · {done}/{js.length} xong
                {active > 0 ? ` · ${active} đang chạy` : ""}
              </span>
              {active > 0 && (
                <button className="btn sm danger" onClick={() => void cancel(b.id)}>
                  Hủy batch
                </button>
              )}
            </div>
            <div className="grid">
              {js.map((j) => (
                <ResultCell key={j.id} job={j} />
              ))}
            </div>
          </section>
        );
      })}
    </main>
  );
}
