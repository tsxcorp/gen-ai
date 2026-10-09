import { useManifests } from "../api/hooks";
import type { Job } from "../api/types";
import { jobModelLabel, jobProvider, PROVIDER_LABEL } from "../lib/providers";

/** "Provider · model" for a result (mixed-provider grids, US14). */
export function ProviderTag({ job }: { job: Pick<Job, "modelId" | "provider"> }) {
  const { data: models = [] } = useManifests();
  const p = jobProvider(job, models);
  return (
    <div className="cap-model" data-testid="cell-model" title={job.modelId}>
      {p && <span className={`badge prov ${p}`}>{PROVIDER_LABEL[p]}</span>} <span>{jobModelLabel(job, models)}</span>
    </div>
  );
}
