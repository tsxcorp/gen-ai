import { useState, type ReactNode } from "react";
import { useManifest, useResolved } from "../api/hooks";
import type { Manifest, ParamDef } from "../api/types";
import { visibleParams } from "../lib/constraints";
import { modelWarnings } from "../lib/manifestMeta";
import { isStalePrice } from "../lib/sweep";
import { PresetsMenu } from "../presets/PresetsMenu";
import { useStudio } from "../store/studio";
import { StatusBadge } from "../ui/Badge";
import { FieldRenderer } from "./FieldRenderer";
import { GenerateFooter } from "./GenerateFooter";
import { PromptField } from "./PromptField";
import { RawRequestTab } from "./RawRequestTab";
import { VariantsPanel } from "./VariantsPanel";
import { useImageSizing } from "./useImageSizing";
import { imageSizingParam } from "../lib/imageSizing";
import { Icon, type IconName } from "../ui/Icon";

export const GROUP_ORDER: [string, string][] = [
  ["size", "Kích thước"],
  ["style", "Phong cách"],
  ["reference", "Tham chiếu"],
  ["audio", "Âm thanh"],
  ["safety", "An toàn"],
  ["output", "Xuất file"],
  ["cost", "Chi phí"],
];

const GROUP_ICONS: Record<string, IconName> = { size: "expand", style: "sparkles", reference: "image", audio: "audio", safety: "shield", output: "download", cost: "sliders" };

function Section({ title, children, defaultOpen = false, count, icon = "sliders" }: { title: string; children: ReactNode; defaultOpen?: boolean; count?: number; icon?: IconName }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="section">
      <button className="section-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <Icon name={icon} /> {title}
        {count !== undefined && <span className="muted"> ({count})</span>}
        <span className={`section-chevron${open ? " open" : ""}`}><Icon name="chevron" /></span>
      </button>
      {open && <div className="section-body">{children}</div>}
    </section>
  );
}

export function ParamPanel() {
  const modelId = useStudio((s) => s.modelId);
  const { data: manifest, isLoading, error } = useManifest(modelId);
  const [tab, setTab] = useState<"params" | "raw">("params");

  if (!modelId) {
    return (
      <div className="panel empty">
        <p className="muted">Chọn một model ở thanh bên trái để bắt đầu.</p>
      </div>
    );
  }
  if (isLoading) return <div className="panel empty">Đang tải manifest…</div>;
  if (error || !manifest) return <div className="panel empty error">Không tải được manifest: {(error as Error)?.message}</div>;
  return <PanelBody key={manifest.id} manifest={manifest} tab={tab} setTab={setTab} />;
}

function PanelBody({ manifest, tab, setTab }: { manifest: Manifest; tab: "params" | "raw"; setTab: (t: "params" | "raw") => void }) {
  const mode = useStudio((s) => s.mode);
  const slots = useStudio((s) => s.slots);
  const setMode = useStudio((s) => s.setMode);
  const setParam = useStudio((s) => s.setParam);
  const setSlot = useStudio((s) => s.setSlot);
  const auto = useStudio((s) => s.autoImageSizing);
  const setAuto = useStudio((s) => s.setAutoImageSizing);
  const sweep = useStudio((s) => s.sweep);
  const requestVersion = useStudio((s) => s.requestVersion);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const sizing = useImageSizing(manifest);
  const baseResolved = useResolved(manifest, mode, sizing.params);
  const sizingParam = imageSizingParam(manifest, mode);
  const sizingConflict = auto && sizingParam && sweep.axes.some((axis) => axis.param === sizingParam.key && axis.values.length > 0)
    ? "Auto theo ảnh gốc không dùng cùng quét tỷ lệ/kích thước. Tắt Auto hoặc gỡ trục quét này." : undefined;
  const sizingError = sizing.error ?? sizingConflict;
  const resolved = sizingError ? { ...baseResolved, errors: [...baseResolved.errors, { key: sizingParam?.key ?? "image", reason: sizingError }] } : baseResolved;

  const visible = visibleParams(manifest, mode).filter((p) => p.key !== "prompt");
  const images = visible.filter((p) => p.type === "image" || p.type === "imageList");
  const controls = visible.filter((p) => p.type !== "image" && p.type !== "imageList");
  const basic = controls.filter((p) => p.level === "basic");
  const rest = controls.filter((p) => p.level !== "basic" && (showAdvanced || p.level !== "advanced"));
  const advancedCount = controls.filter((p) => p.level === "advanced").length;
  const known = new Set(GROUP_ORDER.map(([k]) => k));
  const sections: [string, string, ParamDef[]][] = [
    ...GROUP_ORDER.map(([k, label]): [string, string, ParamDef[]] => [k, label, rest.filter((p) => p.group === k)]),
    ["other", "Khác", rest.filter((p) => !p.group || !known.has(p.group))],
  ];
  const warns = modelWarnings(manifest);

  const field = (p: ParamDef) => (
    <FieldRenderer
      key={`${manifest.id}:${mode}:${requestVersion}:${p.key}`}
      param={p}
      value={resolved.effective[p.key]}
      asset={slots[p.key]}
      lockedReason={resolved.locked[p.key]}
      allowed={resolved.allowed}
      onChange={(v) => { if (p.key === sizingParam?.key) setAuto(false); setParam(p.key, v); }}
      onAsset={(a) => setSlot(manifest, p.key, a)}
      contextKey={`${manifest.id}:${mode}:${requestVersion}:${p.key}`}
      autoSizing={p.key === sizingParam?.key ? { enabled: auto, onChange: setAuto, note: sizing.note, error: sizingError, approximate: sizing.approximate } : undefined}
    />
  );

  return (
    <div className="panel">
      <div className="panel-head">
        <div>
          <strong>{manifest.label ?? manifest.id}</strong> <StatusBadge status={manifest.status} />
        </div>
        <PresetsMenu params={sizing.params} disabled={!!sizingError} />
      </div>
      {warns.map((w) => (
        <div key={w.text} className={`banner ${w.level}`}>
          {w.text}
        </div>
      ))}
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === "params"} className={tab === "params" ? "on" : ""} onClick={() => setTab("params")}>
          <Icon name="sliders" /> Tham số
        </button>
        <button role="tab" aria-selected={tab === "raw"} className={tab === "raw" ? "on" : ""} onClick={() => setTab("raw")}>
          <Icon name="code" /> Request thô
        </button>
      </div>
      <div className="panel-scroll">
        {tab === "raw" ? (
          <RawRequestTab key={requestVersion} manifest={manifest} resolved={resolved} />
        ) : (
          <>
            {manifest.modes.length > 1 && (
              <div className="field">
                <div className="field-label"><Icon name={manifest.kind === "image" ? "image" : "video"} />Chế độ</div>
                <div className="mode-picker" role="radiogroup" aria-label="Chế độ">
                  {manifest.modes.map((value) => (
                    <button type="button" role="radio" aria-checked={mode === value} className={mode === value ? "on" : ""} key={value} onClick={() => setMode(manifest, value)}>
                      <Icon name={value === "edit" ? "edit" : value === "t2i" ? "sparkles" : "video"} />
                      {({ t2i: "Tạo ảnh", edit: "Sửa ảnh", t2v: "Từ mô tả", i2v: "Từ ảnh", first_last: "Đầu / cuối" } as Record<string, string>)[value] ?? value}
                    </button>
                  ))}
                </div>
              </div>
            )}
            <PromptField />
            {images.length > 0 && <div className="input-images">
              <div className="input-images-head"><Icon name="image" /><strong>{mode === "edit" ? "Ảnh gốc để chỉnh sửa" : "Ảnh đầu vào"}</strong></div>
              <p className="field-note">{mode === "edit" ? "Thêm ảnh trước khi sửa. Khi chọn Auto, ảnh đầu tiên quyết định tỷ lệ đầu ra." : "Chọn ảnh cho từng khung hình bên dưới."}</p>
              {images.map(field)}
            </div>}
            {basic.map(field)}
            <Section title="Biến thể & quét tham số" defaultOpen>
              <VariantsPanel manifest={manifest} allowed={resolved.allowed} locked={resolved.locked} />
            </Section>
            {sections.map(
              ([k, label, ps]) =>
                ps.length > 0 && (
                  <Section key={k} title={label} icon={GROUP_ICONS[k] ?? "sliders"} count={ps.length} defaultOpen={ps.some((p) => slots[p.key] !== undefined)}>
                    {ps.map(field)}
                  </Section>
                ),
            )}
            {advancedCount > 0 && (
              <label className="check adv-toggle">
                <input type="checkbox" checked={showAdvanced} onChange={(e) => setShowAdvanced(e.target.checked)} />
                Hiện tham số nâng cao ({advancedCount})
              </label>
            )}
            {resolved.serverError && <p className="warn-text">Không xác nhận được với backend (/api/resolve): {resolved.serverError}. Đang dùng luật cục bộ.</p>}
          </>
        )}
      </div>
      <GenerateFooter resolved={resolved} stale={isStalePrice(manifest.lastVerified)} noPrice={!!manifest.pricing?.lastVerified && isStalePrice(manifest.pricing.lastVerified)} />
    </div>
  );
}
