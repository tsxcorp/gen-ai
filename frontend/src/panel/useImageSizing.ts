import { useEffect, useMemo, useState } from "react";
import { assetUrl } from "../api/client";
import type { Manifest } from "../api/types";
import { firstReference, readImageDimensions, resolveImageSizing, validDimensions } from "../lib/imageSizing";
import { useStudio } from "../store/studio";

export function useImageSizing(manifest: Manifest) {
  const mode = useStudio((state) => state.mode);
  const params = useStudio((state) => state.params);
  const slots = useStudio((state) => state.slots);
  const auto = useStudio((state) => state.autoImageSizing);
  const [failedId, setFailedId] = useState<string | null>(null);
  const source = firstReference(manifest, mode, slots);
  useEffect(() => {
    if (!auto || mode !== "edit" || manifest.kind !== "image" || !source || validDimensions(source.width ?? 0, source.height ?? 0)) return;
    let active = true;
    const id = source.id;
    setFailedId(null);
    void readImageDimensions(assetUrl(id)).then((dimensions) => {
      if (active && useStudio.getState().modelId === manifest.id) {
        setFailedId(null);
        useStudio.getState().setAssetDimensions(id, dimensions);
      }
    }).catch(() => {
      if (active) setFailedId(id);
    });
    return () => { active = false; };
  }, [auto, mode, manifest.id, manifest.kind, source?.id, source?.width, source?.height]);
  const sizing = useMemo(() => resolveImageSizing(manifest, mode, params, slots, auto), [manifest, mode, params, slots, auto]);
  return source?.id === failedId && sizing.error
    ? { ...sizing, error: "Không đọc được kích thước ảnh này. Chọn tỷ lệ/kích thước thủ công hoặc dùng PNG, JPEG, WebP." }
    : sizing;
}
