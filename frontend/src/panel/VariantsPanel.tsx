import { useState } from "react";
import type { Manifest, ParamDef, Scalar, SweepAxis } from "../api/types";
import { enumOptions, visibleParams } from "../lib/constraints";
import { axisWarnings, MAX_AXES, parseAxisValues } from "../lib/sweep";
import { useStudio } from "../store/studio";
import { optionLabel } from "./FieldRenderer";

/** Axis candidates: params that can meaningfully take several values. */
function sweepable(m: Manifest, mode: string): ParamDef[] {
  // invariant 22: an axis on `prompt` is valid (one prompt per line); the base Prompt field must still be non-empty.
  return visibleParams(m, mode).filter((p) => ["enum", "ratio", "int", "float", "bool"].includes(p.type) || p.key === "prompt");
}

function AxisEditor({ axis, params, onChange, onRemove }: { axis: SweepAxis; params: ParamDef[]; onChange: (a: SweepAxis) => void; onRemove: () => void }) {
  const def = params.find((p) => p.key === axis.param);
  const isPrompt = axis.param === "prompt";
  const [text, setText] = useState(axis.values.join(isPrompt ? "\n" : ", "));
  const options = def?.values ?? [];
  const toggle = (v: Scalar) => {
    const has = axis.values.some((x) => String(x) === String(v));
    onChange({ ...axis, values: has ? axis.values.filter((x) => String(x) !== String(v)) : [...axis.values, v] });
  };
  return (
    <div className="axis">
      <div className="row">
        <select
          aria-label="Tham số quét"
          value={axis.param}
          onChange={(e) => {
            setText("");
            onChange({ param: e.target.value, values: [] });
          }}
        >
          <option value="">— chọn tham số —</option>
          {params.map((p) => (
            <option key={p.key} value={p.key}>
              {p.label ?? p.key}
            </option>
          ))}
        </select>
        <button className="btn ghost sm" onClick={onRemove} aria-label="Xóa trục">
          ✕
        </button>
      </div>
      {def && options.length > 0 ? (
        <div className="chips">
          {options.map((o) => (
            <button
              key={String(o)}
              type="button"
              className={`chip${axis.values.some((x) => String(x) === String(o)) ? " on" : ""}`}
              onClick={() => toggle(o)}
            >
              {optionLabel(def, o)}
            </button>
          ))}
        </div>
      ) : isPrompt ? (
        <textarea
          rows={3}
          aria-label="Giá trị trục prompt"
          placeholder={"Mỗi dòng một prompt (ô Prompt chính vẫn phải có nội dung)"}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            onChange({ ...axis, values: parseAxisValues(e.target.value, def?.type ?? "text", "prompt") });
          }}
        />
      ) : (
        def && (
          <input
            placeholder="Giá trị, cách nhau bằng dấu phẩy"
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              onChange({ ...axis, values: parseAxisValues(e.target.value, def.type, def.key) });
            }}
          />
        )
      )}
    </div>
  );
}

export function VariantsPanel({ manifest, allowed, locked = {} }: { manifest: Manifest; allowed: Record<string, Scalar[]>; locked?: Record<string, string> }) {
  const sweep = useStudio((s) => s.sweep);
  const setSweep = useStudio((s) => s.setSweep);
  const text = useStudio((s) => s.promptListText);
  const setText = useStudio((s) => s.setPromptListText);
  const mode = useStudio((s) => s.mode);
  const params = sweepable(manifest, mode).map((p) => (p.values ? { ...p, values: enumOptions(p, allowed) } : p));
  const usedKeys = new Set(sweep.axes.map((a) => a.param));
  const visibleKeys = new Set(visibleParams(manifest, mode).map((p) => p.key));
  const warns = axisWarnings(sweep.axes, visibleKeys, locked);
  const [listOpen, setListOpen] = useState(text.length > 0);

  return (
    <div className="variants">
      <div className="field">
        <label className="field-label" htmlFor="f-n">
          Số bản (N)
        </label>
        <input id="f-n" type="number" min={1} max={64} value={sweep.variants} onChange={(e) => setSweep({ variants: Math.max(1, Number(e.target.value) || 1) })} />
        <div className="field-note">Mỗi lần chạy là ngẫu nhiên (model không đảm bảo tái lập seed).</div>
      </div>

      <label className="check">
        <input
          type="checkbox"
          checked={listOpen}
          onChange={(e) => {
            setListOpen(e.target.checked);
            if (!e.target.checked) setText("");
          }}
        />
        Danh sách prompt (mỗi dòng một prompt, thay cho ô Prompt)
      </label>
      {listOpen && <textarea rows={4} value={text} onChange={(e) => setText(e.target.value)} placeholder={"cảnh 1…\ncảnh 2…"} aria-label="Danh sách prompt" />}

      <div className="field-label">Quét tham số (tối đa {MAX_AXES} trục)</div>
      {sweep.axes.map((a, i) => (
        <AxisEditor
          key={i}
          axis={a}
          params={params.filter((p) => p.key === a.param || !usedKeys.has(p.key))}
          onChange={(na) => setSweep({ axes: sweep.axes.map((x, j) => (j === i ? na : x)) })}
          onRemove={() => setSweep({ axes: sweep.axes.filter((_, j) => j !== i) })}
        />
      ))}
      {warns.map((w) => (
        <p key={w} className="warn-text" role="status">
          {w}
        </p>
      ))}
      {sweep.axes.length < MAX_AXES && (
        <button className="btn sm" onClick={() => setSweep({ axes: [...sweep.axes, { param: "", values: [] }] })}>
          + Thêm trục
        </button>
      )}
    </div>
  );
}
