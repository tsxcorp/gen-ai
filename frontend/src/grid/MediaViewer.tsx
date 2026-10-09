import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { assetUrl } from "../api/client";
import type { Asset } from "../api/types";

export function MediaViewer({ asset, alt, onClose, opener: openingButton }: { asset: Asset; alt: string; onClose: () => void; opener?: HTMLElement | null }) {
  const viewerRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const onCloseRef = useRef(onClose);
  const pendingRef = useRef(false);
  const [notice, setNotice] = useState("");
  onCloseRef.current = onClose;

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    const opener = openingButton ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    const background = Array.from(document.body.children).filter((element): element is HTMLElement => element instanceof HTMLElement && element !== viewer);
    const inertStates = background.map((element) => element.inert);
    const previousOverflow = document.body.style.overflow;
    background.forEach((element) => { element.inert = true; });
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    let ownedFullscreen = false;
    const fullscreenChange = () => {
      if (document.fullscreenElement === viewer || (document.fullscreenElement && viewer.contains(document.fullscreenElement))) ownedFullscreen = true;
      else if (ownedFullscreen) onCloseRef.current();
    };
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        onCloseRef.current();
      }
      if (event.key === "Tab") {
        const buttons = Array.from(viewer.querySelectorAll<HTMLElement>("button:not(:disabled), video[controls]"));
        const first = buttons[0];
        const last = buttons[buttons.length - 1];
        if (event.shiftKey && (document.activeElement === first || !viewer.contains(document.activeElement))) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && (document.activeElement === last || !viewer.contains(document.activeElement))) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    const focusin = (event: FocusEvent) => {
      if (!viewer.contains(event.target as Node)) closeRef.current?.focus();
    };
    window.addEventListener("keydown", keydown, true);
    document.addEventListener("focusin", focusin);
    document.addEventListener("fullscreenchange", fullscreenChange);
    return () => {
      window.removeEventListener("keydown", keydown, true);
      document.removeEventListener("focusin", focusin);
      document.removeEventListener("fullscreenchange", fullscreenChange);
      if (document.fullscreenElement === viewer || (document.fullscreenElement && viewer.contains(document.fullscreenElement))) void document.exitFullscreen().catch(() => {});
      background.forEach((element, index) => { element.inert = inertStates[index] ?? false; });
      document.body.style.overflow = previousOverflow;
      if (opener?.isConnected) opener.focus();
    };
  }, []);

  async function fullscreen() {
    const viewer = viewerRef.current;
    if (!viewer || pendingRef.current || document.fullscreenElement === viewer) return;
    if (!viewer.requestFullscreen || document.fullscreenElement) {
      setNotice("Không thể bật toàn màn hình trình duyệt; vẫn có thể xem lớn tại đây.");
      return;
    }
    pendingRef.current = true;
    try {
      await viewer.requestFullscreen();
      if (!viewer.isConnected && (document.fullscreenElement === viewer || (document.fullscreenElement && viewer.contains(document.fullscreenElement)))) await document.exitFullscreen();
    } catch {
      if (viewer.isConnected) setNotice("Trình duyệt không cho phép toàn màn hình; vẫn có thể xem lớn tại đây.");
    } finally {
      pendingRef.current = false;
    }
  }

  if (typeof document === "undefined") return null;
  return createPortal(
    <div ref={viewerRef} className="media-viewer" role="dialog" aria-modal="true" aria-label={alt || "Xem media toàn màn hình"} onMouseDown={(event) => event.stopPropagation()} onClick={(event) => event.stopPropagation()}>
      <div className="media-viewer-toolbar">
        <span>{alt || "Kết quả"}</span>
        <button type="button" className="btn" onClick={() => void fullscreen()}>Toàn màn hình trình duyệt</button>
        <button ref={closeRef} type="button" className="btn" onClick={onClose} aria-label="Đóng trình xem">Đóng ✕</button>
      </div>
      {notice && <div className="media-viewer-notice" role="status">{notice}</div>}
      <div className="media-viewer-content">
        {asset.mime.startsWith("video/") ? (
          <video src={assetUrl(asset.id)} controls tabIndex={0} preload="metadata" playsInline aria-label={alt || "Video kết quả"} />
        ) : (
          <img src={assetUrl(asset.id)} alt={alt} />
        )}
      </div>
    </div>,
    document.body,
  );
}
