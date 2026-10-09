import { AssetView, jobWarnings } from "../grid/AssetView";
import { ProviderTag } from "../grid/ProviderTag";
import { diffKeys, jobPrompt } from "../lib/job";
import { useStudio } from "../store/studio";
import { Modal } from "../ui/Modal";

export function CompareModal() {
  const open = useStudio((s) => s.compareOpen);
  const setOpen = useStudio((s) => s.setCompare);
  const selected = useStudio((s) => s.selected);
  const jobs = useStudio((s) => s.jobs);
  if (!open) return null;
  const list = selected.map((id) => jobs[id]).filter((j): j is NonNullable<typeof j> => !!j).slice(0, 4);
  const diff = diffKeys(list);
  return (
    <Modal title={`So sánh ${list.length} kết quả`} onClose={() => setOpen(false)} wide>
      <div className="compare" style={{ gridTemplateColumns: `repeat(${list.length}, minmax(0, 1fr))` }}>
        {list.map((j) => {
          return (
            <div key={j.id} className="compare-col">
              {j.assets.map((a, i) => (
                <div key={a.id} className="compare-asset" data-testid="compare-asset">
                  <AssetView asset={a} alt={`${jobPrompt(j).slice(0, 60)} (#${i + 1})`} lazy={false} />
                  {j.assets.length > 1 && <span className="asset-tag">#{i + 1}</span>}
                </div>
              ))}
              {jobWarnings(j).map((w, i) => (
                <div key={`${i}:${w}`} className="warn-text">
                  {w}
                </div>
              ))}
              <ProviderTag job={j} />
              <div className="cap-prompt">{jobPrompt(j)}</div>
              <table className="params">
                <tbody>
                  <tr>
                    <td>model</td>
                    <td>{j.modelId}</td>
                  </tr>
                  {Object.entries(j.effectiveParams).map(([k, v]) => (
                    <tr key={k} className={diff.has(k) ? "diff" : ""}>
                      <td>{k}</td>
                      <td>{typeof v === "object" ? JSON.stringify(v) : String(v)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        })}
      </div>
    </Modal>
  );
}
