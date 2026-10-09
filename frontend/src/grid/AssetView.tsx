import { assetUrl } from "../api/client";
import { useRef, useState } from "react";
import type { Asset, Job } from "../api/types";
import { MediaViewer } from "./MediaViewer";

/** One output asset (image or video). Plain `/api/assets/{id}` URL: the session cookie authenticates. */
export function AssetView({ asset, alt, controls = true, lazy = true }: { asset: Asset; alt: string; controls?: boolean; lazy?: boolean }) {
  const [open, setOpen] = useState(false);
  const openerRef = useRef<HTMLButtonElement>(null);
  const isVideo = asset.mime.startsWith("video/");
  return (
    <div className="asset-view">
      {isVideo ? (
        <video src={assetUrl(asset.id)} controls={controls} preload="metadata" loop playsInline />
      ) : (
        <img src={assetUrl(asset.id)} alt={alt} loading={lazy ? "lazy" : undefined} />
      )}
      <button ref={openerRef} type="button" className="asset-expand" aria-label={isVideo ? "Xem video toàn màn hình" : "Xem ảnh toàn màn hình"} title="Xem toàn màn hình" onClick={() => setOpen(true)}>
        ⛶
      </button>
      {open && <MediaViewer asset={asset} alt={alt} opener={openerRef.current} onClose={() => setOpen(false)} />}
    </div>
  );
}

/** Warnings to show for a job: backend `warnings` plus a local note when fewer assets than variantCount arrived. */
export function jobWarnings(job: Job): string[] {
  const out = [...(job.warnings ?? [])];
  const want = job.variantCount ?? 1;
  if (job.status === "succeeded" && job.assets.length < want && out.length === 0) {
    out.push(`Chỉ nhận ${job.assets.length}/${want} kết quả của nhóm này (một phần có thể bị lọc).`);
  }
  return out;
}

export function extOf(mime: string): string {
  const sub = mime.split("/")[1] ?? "bin";
  return sub === "jpeg" ? "jpg" : sub;
}
