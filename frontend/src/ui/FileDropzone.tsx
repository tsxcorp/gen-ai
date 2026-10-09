import { useId, useRef, useState } from "react";
import { Icon } from "./Icon";

export function formatFileSize(bytes: number): string {
  return bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`;
}

export function validateFiles(files: File[], accept: string, maxBytes: number, maxFiles: number): string | null {
  if (!files.length) return "Chưa chọn file.";
  if (files.length > maxFiles) return `Chỉ được chọn tối đa ${maxFiles} file.`;
  const accepted = accept.toLowerCase().split(",").map((entry) => entry.trim()).filter(Boolean);
  for (const file of files) {
    if (!file.size) return `File ${file.name} đang trống.`;
    if (file.size > maxBytes) return `File ${file.name} vượt giới hạn ${formatFileSize(maxBytes)}.`;
    const matches = accepted.some((entry) => entry.startsWith(".") ? file.name.toLowerCase().endsWith(entry)
      : entry.endsWith("/*") ? file.type.toLowerCase().startsWith(entry.slice(0, -1)) : file.type.toLowerCase() === entry);
    if (accepted.length && !matches) return `Định dạng file ${file.name} không được hỗ trợ.`;
  }
  return null;
}

export interface FileDropzoneProps {
  accept: string;
  maxBytes: number;
  maxFiles: number;
  onFiles: (files: File[]) => void;
  label: string;
  hint?: string;
  disabled?: boolean;
  busy?: boolean;
  pasteImages?: boolean;
  selectedFiles?: File[];
}

export function FileDropzone({ accept, maxBytes, maxFiles, onFiles, label, hint, disabled, busy, pasteImages, selectedFiles = [] }: FileDropzoneProps) {
  const input = useRef<HTMLInputElement>(null);
  const id = useId();
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const locked = disabled || busy;
  function receive(files: File[]) {
    if (locked) return;
    const problem = validateFiles(files, accept, maxBytes, maxFiles);
    setError(problem);
    if (!problem) onFiles(files);
  }
  return <div className="file-uploader">
    <div className={`file-dropzone${dragging && !locked ? " dragging" : ""}${locked ? " disabled" : ""}`} aria-busy={busy || undefined}
      onDragOver={(event) => { event.preventDefault(); if (!locked) setDragging(true); }}
      onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false); }}
      onDrop={(event) => { event.preventDefault(); setDragging(false); if (!locked) receive(Array.from(event.dataTransfer.files)); }}
      onPaste={(event) => {
        if (!pasteImages || locked) return;
        const images = Array.from(event.clipboardData.items).filter((item) => item.kind === "file" && item.type.startsWith("image/"))
          .map((item) => item.getAsFile()).filter((file): file is File => file !== null);
        if (images.length) { event.preventDefault(); receive(images); }
      }}>
      <button type="button" className="dropzone-picker" disabled={locked} aria-describedby={`${id}-hint${error ? ` ${id}-error` : ""}`}
        onClick={() => { if (!locked) input.current?.click(); }}>
        <span className="dropzone-symbol"><Icon name={pasteImages ? "image" : "file"} /></span>
        <strong>{busy ? "Đang xử lý file…" : selectedFiles.length ? "Thay file đã chọn" : label}</strong>
        <span id={`${id}-hint`} className="field-note">{hint ?? "Kéo thả hoặc bấm để chọn file"}</span>
        {pasteImages && <span className="paste-hint"><Icon name="clipboard" /> Dán ảnh khi focus vùng này · Ctrl/Cmd+V</span>}
      </button>
      <input ref={input} className="visually-hidden" type="file" accept={accept} multiple={maxFiles > 1} disabled={locked}
        aria-label={label} onChange={(event) => { if (event.target.files?.length) receive(Array.from(event.target.files)); event.target.value = ""; }} />
    </div>
    {selectedFiles.length > 0 && <ul className="selected-files">{selectedFiles.map((file, index) =>
      <li key={`${file.name}-${index}`}><Icon name="file" /><span>{file.name}</span><small>{formatFileSize(file.size)}</small></li>)}</ul>}
    {error && <p id={`${id}-error`} role="alert" className="error">{error}</p>}
  </div>;
}
