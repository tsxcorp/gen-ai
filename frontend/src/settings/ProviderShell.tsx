import { useState, type ReactNode } from "react";
import type { UseMutationResult } from "@tanstack/react-query";
import { Modal } from "../ui/Modal";

type Test = UseMutationResult<{ ok?: boolean; message?: string }, Error, void>;
type Mut = UseMutationResult<unknown, Error, void>;

/** Shared chrome of a provider section: badge, Save / Test / Delete (confirm), result messages. */
export function ProviderShell({
  title,
  configured,
  children,
  canSave,
  save,
  test,
  remove,
}: {
  title: string;
  configured: boolean;
  children: ReactNode;
  canSave: boolean;
  save: Mut;
  test: Test;
  remove: Mut;
}) {
  const [confirm, setConfirm] = useState(false);
  return (
    <section aria-label={title}>
      <h2 className="prov-title">
        {title}{" "}
        <span className={`badge ${configured ? "ok" : "stale"}`} data-testid="configured-badge">
          {configured ? "đã cấu hình" : "chưa cấu hình"}
        </span>
      </h2>
      <p className="field-note">Key chỉ được ghi vào backend (data/providers.json, quyền 600) và không bao giờ được hiển thị lại.</p>
      {children}
      <div className="row">
        <button className="btn primary" disabled={!canSave || save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? "Đang lưu…" : "Lưu"}
        </button>
        <button className="btn" disabled={test.isPending} onClick={() => test.mutate()}>
          {test.isPending ? "Đang kiểm tra…" : "Test kết nối"}
        </button>
        <button className="btn danger" disabled={!configured || remove.isPending} onClick={() => setConfirm(true)}>
          Xóa cấu hình
        </button>
      </div>
      {save.isSuccess && <p className="ok-text">Đã lưu.</p>}
      {save.error && <p className="error">{save.error.message}</p>}
      {test.isSuccess && <p className={test.data.ok === false ? "error" : "ok-text"}>{test.data.ok === false ? `Thất bại: ${test.data.message ?? ""}` : "Kết nối OK."}</p>}
      {test.error && <p className="error">{test.error.message}</p>}
      {remove.error && <p className="error">{remove.error.message}</p>}
      {confirm && (
        <Modal title={`Xóa cấu hình ${title}?`} onClose={() => setConfirm(false)}>
          <p>Key và cấu hình của provider này sẽ bị xóa khỏi backend. Provider khác không bị ảnh hưởng.</p>
          <div className="row end">
            <button className="btn" onClick={() => setConfirm(false)}>
              Hủy
            </button>
            <button
              className="btn danger"
              onClick={() => {
                setConfirm(false);
                remove.mutate();
              }}
            >
              Xóa
            </button>
          </div>
        </Modal>
      )}
    </section>
  );
}
