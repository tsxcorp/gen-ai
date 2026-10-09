import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { api, assetUrl } from "../api/client";
import type { Asset, ParamDef } from "../api/types";
import { FileDropzone, formatFileSize, validateFiles } from "../ui/FileDropzone";
import { Icon } from "../ui/Icon";
import { useStudio } from "../store/studio";

interface Props {
  param: ParamDef;
  value: Asset | Asset[] | undefined;
  onChange: (value: Asset | Asset[] | null) => void;
  disabled?: boolean;
  contextKey?: string;
}
interface StagedFile { file: File; url: string }
const ACCEPT = "image/png,image/jpeg,image/webp,image/heic,image/heif,.png,.jpg,.jpeg,.webp,.heic,.heif";
const MAX_BYTES = 20 * 1024 * 1024;

function dimensions(url: string): Promise<{ width: number; height: number } | undefined> {
  return new Promise((resolve) => {
    const image = new Image();
    const timer = setTimeout(() => finish(undefined), 8000);
    function finish(size: { width: number; height: number } | undefined) {
      clearTimeout(timer);
      image.onload = null;
      image.onerror = null;
      resolve(size);
    }
    image.onload = () => finish(image.naturalWidth > 0 && image.naturalHeight > 0 ? { width: image.naturalWidth, height: image.naturalHeight } : undefined);
    image.onerror = () => finish(undefined);
    image.src = url;
  });
}

export function ReferenceUpload({ param, value, onChange, disabled, contextKey = "" }: Props) {
  const { modelId, mode, requestVersion } = useStudio.getState();
  const multi = param.type === "imageList";
  const list = value === undefined ? [] : Array.isArray(value) ? value : [value];
  const max = multi ? param.maxItems ?? (Array.isArray(param.range) ? param.range[1] : param.range?.max) ?? 14 : 1;
  const [staged, setStaged] = useState<StagedFile[]>([]);
  const [hasPerson, setHasPerson] = useState(false);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const stagedRef = useRef(staged);
  const generation = useRef(0);
  const uploading = useRef(false);
  const current = useRef({ list, onChange, disabled, max });
  useLayoutEffect(() => { current.current = { list, onChange, disabled, max }; });
  function replaceStaged(next: StagedFile[]) {
    stagedRef.current.filter((entry) => !next.includes(entry)).forEach((entry) => URL.revokeObjectURL(entry.url));
    stagedRef.current = next;
    setStaged(next);
  }
  useLayoutEffect(() => {
    generation.current += 1;
    uploading.current = false;
    replaceStaged([]);
    setBusy(false);
    setConsent(false);
    setHasPerson(false);
    setError(null);
    return () => { generation.current += 1; };
  }, [contextKey, param.key]);
  useEffect(() => () => { stagedRef.current.forEach((entry) => URL.revokeObjectURL(entry.url)); }, []);

  function select(files: File[]) {
    if (disabled || uploading.current) return;
    const problem = validateFiles(files, ACCEPT, MAX_BYTES, Math.max(0, max - list.length));
    setError(problem);
    if (problem) return;
    try {
      const next: StagedFile[] = [];
      try { files.forEach((file) => next.push({ file, url: URL.createObjectURL(file) })); }
      catch (cause) { next.forEach((entry) => URL.revokeObjectURL(entry.url)); throw cause; }
      replaceStaged(next);
      setConsent(false);
      setHasPerson(false);
    } catch { setError("Không thể tạo preview cho file đã chọn."); }
  }

  async function upload() {
    if (disabled || uploading.current || !consent || !stagedRef.current.length) return;
    function contextMatches() {
      const live = useStudio.getState();
      return live.modelId === modelId && live.mode === mode && live.requestVersion === requestVersion;
    }
    function liveList(): Asset[] {
      if (!contextKey) return current.current.list;
      const slot = useStudio.getState().slots[param.key];
      return slot === undefined ? [] : Array.isArray(slot) ? slot : [slot];
    }
    function checkCapacity(count: number) {
      if (liveList().length + count > current.current.max) {
        throw new Error("Số ảnh trong slot đã thay đổi và vượt giới hạn. Gỡ bớt ảnh trước khi thử lại; các file chưa dùng vẫn được giữ.");
      }
    }
    if (!contextMatches()) return;
    const problem = validateFiles(stagedRef.current.map((entry) => entry.file), ACCEPT, MAX_BYTES, Math.max(0, current.current.max - liveList().length));
    if (problem) { setError(problem); return; }
    const token = generation.current;
    const pending = [...stagedRef.current];
    uploading.current = true;
    setBusy(true);
    setError(null);
    try {
      for (const [index, entry] of pending.entries()) {
        if (token !== generation.current || current.current.disabled || !contextMatches()) return;
        checkCapacity(pending.length - index);
        const size = await dimensions(entry.url);
        if (token !== generation.current || current.current.disabled || !contextMatches()) return;
        checkCapacity(pending.length - index);
        const uploaded = await api.upload(entry.file, hasPerson, consent);
        if (token !== generation.current || current.current.disabled || !contextMatches()) return;
        checkCapacity(1);
        const asset: Asset = { ...uploaded, ...size, name: entry.file.name };
        const next = [...liveList(), asset];
        if (!contextMatches()) return;
        checkCapacity(1);
        current.current = { ...current.current, list: next };
        current.current.onChange(multi ? next : asset);
        replaceStaged(stagedRef.current.filter((item) => item !== entry));
      }
      setConsent(false);
      setHasPerson(false);
    } catch (cause) {
      if (token === generation.current && contextMatches()) setError(cause instanceof Error ? cause.message : "Không thể tải ảnh. Các ảnh chưa thành công vẫn được giữ để thử lại.");
    } finally {
      if (token === generation.current) { uploading.current = false; setBusy(false); }
    }
  }

  return <div className="ref-upload" aria-busy={busy || undefined}>
    {list.length > 0 && <div className="reference-previews">{list.map((asset) => <div className="reference-preview" key={asset.id}>
      <img src={assetUrl(asset.id)} alt={asset.name ?? param.label ?? param.key} />
      <div className="preview-details"><strong>{asset.name ?? "Ảnh đã tải"}</strong><small>{asset.width && asset.height ? `${asset.width} × ${asset.height}` : "Ảnh gốc"}</small></div>
      <button type="button" className="preview-remove" aria-label={`Gỡ ảnh ${asset.name ?? asset.id}`} disabled={disabled || busy} onClick={() => {
        if (disabled || uploading.current) return;
        const rest = current.current.list.filter((entry) => entry.id !== asset.id);
        current.current.onChange(multi ? rest : null);
      }}><Icon name="close" /></button>
    </div>)}</div>}
    {list.length < max && <FileDropzone accept={ACCEPT} maxBytes={MAX_BYTES} maxFiles={Math.max(0, max - list.length)}
      onFiles={select} label={staged.length ? "Thay ảnh đang chờ" : "Chọn ảnh tham chiếu"} hint={`PNG, JPEG, WebP, HEIC, HEIF · tối đa 20 MB/ảnh · còn ${max - list.length} ảnh`}
      pasteImages disabled={disabled} busy={busy} />}
    {staged.length > 0 && <div className="upload-box">
      <div className="reference-previews staged-previews">{staged.map((entry) => <div className="reference-preview" key={entry.url}>
        <img src={entry.url} alt={entry.file.name} />
        <div className="preview-details"><strong>{entry.file.name}</strong><small>{formatFileSize(entry.file.size)} · chờ xác nhận</small></div>
        <button type="button" className="preview-remove" aria-label={`Gỡ file ${entry.file.name}`} disabled={disabled || busy} onClick={() => {
          if (disabled || uploading.current) return;
          replaceStaged(stagedRef.current.filter((item) => item !== entry)); setConsent(false); setHasPerson(false);
        }}><Icon name="close" /></button>
      </div>)}</div>
      <label className="check"><input type="checkbox" checked={hasPerson} disabled={disabled || busy} onChange={(event) => setHasPerson(event.target.checked)} />Ảnh có người</label>
      {hasPerson && <p className="warn-text">Ảnh có người có thể bị provider chặn hoặc ảnh hưởng quyền riêng tư. Chỉ dùng ảnh khi có quyền và sự đồng ý phù hợp.</p>}
      <p className="field-note">Ảnh chỉ được gửi lên sau khi bạn xác nhận quyền sử dụng. Giữ nguyên file gốc, không chuyển đổi ảnh.</p>
      <label className="check"><input type="checkbox" checked={consent} disabled={disabled || busy} onChange={(event) => setConsent(event.target.checked)} />Tôi có quyền dùng tất cả ảnh đã chọn</label>
      <button type="button" className="btn upload-submit" disabled={disabled || busy || !consent} onClick={() => void upload()}><Icon name="upload" />{busy ? "Đang tải lên…" : `Tải lên & dùng ${staged.length} ảnh`}</button>
    </div>}
    {error && <p className="error" role="alert">{error}</p>}
  </div>;
}
