import type { Asset, ParamDef, ParamValue, Scalar } from "../api/types";
import { enumOptions, paramRange } from "../lib/constraints";
import { ReferenceUpload } from "./ReferenceUpload";
import { Icon, RatioIcon, type IconName } from "../ui/Icon";

interface Props {
  param: ParamDef;
  value: ParamValue | undefined;
  asset: Asset | Asset[] | undefined;
  lockedReason?: string;
  allowed: Record<string, Scalar[]>;
  onChange: (v: ParamValue | undefined) => void;
  onAsset: (v: Asset | Asset[] | null) => void;
  contextKey?: string;
  autoSizing?: { enabled: boolean; onChange: (enabled: boolean) => void; note?: string; error?: string; approximate?: boolean };
}

export function optionLabel(p: ParamDef, v: Scalar): string {
  return p.valueLabels?.[String(v)] ?? String(v);
}

export function FieldRenderer({ param: p, value, asset, lockedReason, allowed, onChange, onAsset, autoSizing, contextKey }: Props) {
  const locked = lockedReason !== undefined;
  const id = `f-${p.key}`;
  const label = p.label ?? p.key;
  const hasDefault = p.default !== undefined;
  const icons: Record<string, IconName> = { size: "expand", style: "sparkles", reference: "image", audio: "audio", safety: "shield", output: "download", cost: "sliders" };
  const icon = icons[p.group ?? ""] ?? "sliders";
  const ratio = p.type === "ratio" || p.key === "aspect_ratio";
  const autoButton = autoSizing && (
    <button type="button" role="radio" aria-checked={autoSizing.enabled} className={`ratio-option${autoSizing.enabled ? " on" : ""}`} disabled={locked} onClick={() => autoSizing.onChange(true)}>
      <RatioIcon value="auto" /><span>Auto<small>Theo ảnh gốc</small></span>
    </button>
  );

  let control: JSX.Element;
  if (p.type === "enum" || p.type === "ratio") {
    const opts = enumOptions(p, allowed);
    if (ratio) {
      control = (
        <div className="ratio-options" role="radiogroup" aria-label={label}>
          {autoButton}
          {opts.map((option) => (
            <button key={String(option)} type="button" role="radio" aria-checked={!autoSizing?.enabled && String(value) === String(option)}
              className={`ratio-option${!autoSizing?.enabled && String(value) === String(option) ? " on" : ""}`} disabled={locked}
              onClick={() => { autoSizing?.onChange(false); onChange(option); }}>
              <RatioIcon value={String(option)} /><span>{optionLabel(p, option)}</span>
            </button>
          ))}
        </div>
      );
    } else if (opts.length > 0 && opts.length <= 5 && hasDefault) {
      control = (
        <div className="seg" role="radiogroup" aria-label={label}>
          {opts.map((o) => (
            <button
              key={String(o)}
              type="button"
              role="radio"
              aria-checked={String(value) === String(o)}
              className={String(value) === String(o) ? "on" : ""}
              disabled={locked}
              onClick={() => onChange(o)}
            >
              <Icon name={icon} />
              {optionLabel(p, o)}
            </button>
          ))}
        </div>
      );
    } else {
      control = (
        <select
          id={id}
          value={value === undefined || value === null ? "" : String(value)}
          disabled={locked}
          onChange={(e) => {
            const raw = e.target.value;
            if (raw === "") return onChange(undefined);
            onChange(opts.find((o) => String(o) === raw) ?? raw);
          }}
        >
          {!hasDefault && <option value="">(mặc định)</option>}
          {opts.map((o) => (
            <option key={String(o)} value={String(o)}>
              {optionLabel(p, o)}
            </option>
          ))}
        </select>
      );
    }
  } else if (p.type === "int" || p.type === "float") {
    const r = paramRange(p);
    control = (
      <input
        id={id}
        type="number"
        value={value === undefined || value === null ? "" : String(value)}
        min={r?.min}
        max={r?.max}
        step={r?.step ?? (p.type === "int" ? 1 : "any")}
        disabled={locked}
        onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))}
      />
    );
  } else if (p.type === "bool") {
    control = (
      <label className="check">
        <input id={id} type="checkbox" checked={value === true} disabled={locked} onChange={(e) => onChange(e.target.checked)} />
        {value === true ? "Bật" : "Tắt"}
      </label>
    );
  } else if (p.type === "image" || p.type === "imageList") {
    control = <ReferenceUpload param={p} value={asset} onChange={onAsset} disabled={locked} contextKey={contextKey} />;
  } else {
    control = (
      <>
        {autoSizing && <div className="ratio-options" role="radiogroup" aria-label={`${label} tự động`}>{autoButton}</div>}
        <input id={id} type="text" value={typeof value === "string" ? value : ""} disabled={locked || autoSizing?.enabled} onChange={(e) => onChange(e.target.value || undefined)} />
        {autoSizing?.enabled && <button type="button" className="link" disabled={locked} onClick={() => autoSizing.onChange(false)}>Chọn kích thước thủ công</button>}
        {p.suggestions && <div className="chips size-suggestions">
          {p.suggestions.filter((suggestion) => !autoSizing || suggestion !== "auto").map((suggestion) => (
            <button type="button" className="chip" key={suggestion} disabled={locked} onClick={() => { autoSizing?.onChange(false); onChange(suggestion); }}><Icon name="expand" />{suggestion}</button>
          ))}
        </div>}
      </>
    );
  }

  return (
    <div className={`field${locked ? " locked" : ""}`} data-key={p.key}>
      <label htmlFor={id} className="field-label">
        <Icon name={icon} />
        {label}
        {locked && (
          <span className="lock" title={lockedReason} aria-label={`Khóa: ${lockedReason}`}>
            <Icon name="lock" />
          </span>
        )}
      </label>
      {control}
      {autoSizing?.enabled && (autoSizing.note || autoSizing.error) && <p className={`sizing-note ${autoSizing.error ? "error" : autoSizing.approximate ? "warn-text" : "muted"}`} role="status">{autoSizing.error ?? autoSizing.note}</p>}
      {locked && <div className="field-note">{lockedReason}</div>}
      {!locked && p.description && <div className="field-note">{p.description}</div>}
    </div>
  );
}
