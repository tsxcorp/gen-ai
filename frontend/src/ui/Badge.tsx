import type { ModelStatus } from "../api/types";

export function StatusBadge({ status }: { status: ModelStatus }) {
  if (status === "ga") return null;
  return <span className={`badge ${status}`}>{status}</span>;
}
