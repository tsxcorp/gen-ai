import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { establishSession, getToken, setToken, setUnauthorizedHandler } from "./api/client";
import { CompareModal } from "./compare/CompareModal";
import { ResultsGrid } from "./grid/ResultsGrid";
import { ModelSidebar } from "./panel/ModelSidebar";
import { ParamPanel } from "./panel/ParamPanel";
import { SettingsPage } from "./settings/SettingsPage";
import { useLiveSync } from "./store/sync";
import { useStudio } from "./store/studio";
import { Modal } from "./ui/Modal";
import { Icon } from "./ui/Icon";

function TokenDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const [v, setV] = useState("");
  return (
    <Modal title="Cần token truy cập" onClose={onClose}>
      <p>Backend đang chạy ở chế độ LAN và yêu cầu token (in ra terminal khi khởi động).</p>
      <input type="password" autoFocus value={v} onChange={(e) => setV(e.target.value)} aria-label="Token" />
      <div className="row end">
        <button
          className="btn primary"
          disabled={!v.trim()}
          onClick={() => {
            setToken(v.trim());
            // cookie first so asset URLs work, then refetch everything
            void establishSession().then(() => qc.invalidateQueries());
            onClose();
          }}
        >
          Dùng token
        </button>
      </div>
    </Modal>
  );
}

export function App() {
  const page = useStudio((s) => s.page);
  const setPage = useStudio((s) => s.setPage);
  const [needToken, setNeedToken] = useState(false);
  useLiveSync();
  useEffect(() => {
    setUnauthorizedHandler(() => setNeedToken(true));
  }, []);

  return (
    <div className="app">
      <header className="topbar">
        <strong className="brand"><Icon name="sparkles" />AI Gen Studio</strong>
        <nav>
          <button className={page === "studio" ? "on" : ""} onClick={() => setPage("studio")}>
            <Icon name="grid" /> Studio
          </button>
          <button className={page === "settings" ? "on" : ""} onClick={() => setPage("settings")}>
            <Icon name="settings" /> Cài đặt
          </button>
        </nav>
        <span className="spacer" />
        {getToken() && (
          <button className="btn ghost sm" onClick={() => setToken(null)} title="Xóa token đã lưu">
            Xóa token
          </button>
        )}
      </header>
      {page === "settings" ? (
        <SettingsPage />
      ) : (
        <div className="studio">
          <ModelSidebar />
          <ParamPanel />
          <ResultsGrid />
        </div>
      )}
      <CompareModal />
      {needToken && <TokenDialog onClose={() => setNeedToken(false)} />}
    </div>
  );
}
