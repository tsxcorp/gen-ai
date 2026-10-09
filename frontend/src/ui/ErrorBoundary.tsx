import { Component, type ErrorInfo, type ReactNode } from "react";
import { api } from "../api/client";
import { saveBlob } from "../lib/download";
import { unsavedAssetIds, useStudio } from "../store/studio";

interface State {
  error: Error | null;
  zipBusy: boolean;
  zipErr: string | null;
}

/**
 * Root error boundary (invariant 24). Zustand state (prompt, sweep, results, downloaded flags)
 * lives outside the React tree, so "Thử lại" re-mounts the UI WITHOUT losing it. Unsaved results are
 * announced and can be zipped from here even if the tree keeps crashing.
 */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null, zipBusy: false, zipErr: null };

  static getDerivedStateFromError(error: unknown): Partial<State> {
    return { error: error instanceof Error ? error : new Error(String(error)) };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("UI crashed:", error, info.componentStack);
  }

  private retry = () => this.setState({ error: null, zipErr: null });

  private downloadUnsaved = async () => {
    const s = useStudio.getState();
    const ids = unsavedAssetIds(s.jobs, s.downloaded);
    if (ids.length === 0) return;
    this.setState({ zipBusy: true, zipErr: null });
    try {
      saveBlob(await api.zip(ids), "ai-gen-studio-recovered.zip");
      s.markDownloaded(ids);
    } catch (e) {
      this.setState({ zipErr: (e as Error).message });
    } finally {
      this.setState({ zipBusy: false });
    }
  };

  render(): ReactNode {
    const { error, zipBusy, zipErr } = this.state;
    if (!error) return this.props.children;
    const s = useStudio.getState();
    const unsaved = unsavedAssetIds(s.jobs, s.downloaded).length;
    return (
      <div className="crash" role="alert" style={{ maxWidth: 640, margin: "10vh auto", padding: 24 }}>
        <h2>Giao diện gặp lỗi</h2>
        <p className="error">{error.message}</p>
        <p>
          Dữ liệu trong bộ nhớ (prompt, tham số, kết quả) <strong>chưa bị xóa</strong>. Nhấn &quot;Thử lại&quot; để dựng lại giao diện mà không mất gì.
          Nếu lỗi lặp lại, tải kết quả chưa lưu trước khi tải lại trang.
        </p>
        <div className="row">
          <button className="btn primary" onClick={this.retry}>
            Thử lại
          </button>
          {unsaved > 0 && (
            <button className="btn" disabled={zipBusy} onClick={() => void this.downloadUnsaved()}>
              Tải kết quả chưa lưu ({unsaved}) .zip
            </button>
          )}
          <button className="btn ghost" onClick={() => window.location.reload()}>
            Tải lại trang (mất kết quả chưa tải)
          </button>
        </div>
        {zipErr && <p className="error">{zipErr}</p>}
        <details>
          <summary>Chi tiết kỹ thuật</summary>
          <pre style={{ whiteSpace: "pre-wrap" }}>{error.stack ?? error.message}</pre>
        </details>
      </div>
    );
  }
}
