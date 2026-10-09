import { useEffect, useRef } from "react";
import type { Resolved } from "../api/hooks";
import { footerLabel, formatRange } from "../lib/sweep";
import { PROVIDER_LABEL } from "../lib/providers";
import { useStudio } from "../store/studio";
import { Modal } from "../ui/Modal";
import { ErrorList } from "./ErrorList";
import { useGenerate } from "./useGenerate";
import { Icon } from "../ui/Icon";

export function GenerateFooter({ resolved, stale, noPrice }: { resolved: Resolved; stale: boolean; noPrice: boolean }) {
  const g = useGenerate(resolved);
  const openSettings = useStudio((s) => s.openSettings);
  const ref = useRef(g.generate);
  ref.current = g.generate;

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        void ref.current();
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  const est = g.estimate.data;
  const jobs = est?.jobCount ?? g.localCount;
  const warnings = est?.warnings ?? [];

  return (
    <footer className="gen-footer">
      <ErrorList errors={g.conflict ? [...resolved.errors, { key: "sweep", reason: g.conflict }] : resolved.errors} />
      {g.estimate.error && <p className="error">{(g.estimate.error as Error).message}</p>}
      {est?.unknownPrice && (
        <p className="warn-text">Có job chưa biết giá: ước tính bên dưới không phải mức trần, cần xác nhận trước khi chạy.</p>
      )}
      {warnings.map((w, i) => (
        <p key={`${i}:${w}`} className="warn-text" role="status">
          {w}
        </p>
      ))}
      {(stale || noPrice) && <p className="warn-text">Giá có thể cũ (manifest/giá kiểm lần cuối &gt; 30 ngày).</p>}
      {g.notConfigured && (
        <p className="warn-text" role="alert" data-testid="not-configured">
          {g.notConfigured}{" "}
          {g.notConfiguredProvider && (
            <button className="link" onClick={() => openSettings(g.notConfiguredProvider!)}>
              Mở Cài đặt {PROVIDER_LABEL[g.notConfiguredProvider]}
            </button>
          )}
        </p>
      )}
      {g.error && <p className="error">{g.error}</p>}
      <div className="gen-row">
        <div className="summary" aria-live="polite" title="Ước tính từ POST /api/estimate">
          {footerLabel(jobs, est)}
          {g.estimate.isFetching && <span className="muted"> ↻</span>}
        </div>
        <button className="btn primary big" disabled={!g.canGenerate} onClick={() => void g.generate()}>
          <Icon name="sparkles" />
          {g.submitting ? "Đang gửi…" : "Generate"} <kbd>⌘↵</kbd>
        </button>
      </div>
      {g.pending && (
        <Modal title="Xác nhận chi phí" onClose={g.cancelConfirm}>
          <p>
            Batch này gồm <strong>{g.pending.est.jobCount} job</strong>, ước tính <strong>{formatRange(g.pending.est.minUsd, g.pending.est.maxUsd)}</strong>
            {g.pending.est.thresholdUsd !== undefined && <> (vượt ngưỡng ${g.pending.est.thresholdUsd})</>}. Đây là tiền thật trên tài khoản provider của bạn.
          </p>
          <div className="row end">
            <button className="btn" onClick={g.cancelConfirm}>
              Hủy
            </button>
            <button className="btn primary" onClick={g.confirm} disabled={g.submitting}>
              Xác nhận và chạy
            </button>
          </div>
        </Modal>
      )}
    </footer>
  );
}
