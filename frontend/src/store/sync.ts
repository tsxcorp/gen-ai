import { useEffect } from "react";
import { api } from "../api/client";
import { connectEvents } from "../api/sse";
import { isActive, normalizeJob } from "../lib/job";
import { hasRunning, unsavedAssetIds, useStudio } from "./studio";

function applyEvent(event: string, data: unknown): void {
  const st = useStudio.getState();
  const d = (data ?? {}) as Record<string, unknown>;
  if (event === "job.updated") {
    const raw = (d["job"] ?? d) as unknown;
    if ((raw as { id?: unknown }).id) st.upsertJob(normalizeJob(raw));
  } else if (event === "batch.updated") {
    const jobs = (d["jobs"] ?? (d["batch"] as { jobs?: unknown[] } | undefined)?.jobs) as unknown[] | undefined;
    jobs?.forEach((j) => st.upsertJob(normalizeJob(j)));
  }
}

async function resyncActive(): Promise<void> {
  const st = useStudio.getState();
  const ids = st.batches.filter((b) => b.jobIds.some((id) => st.jobs[id] && isActive(st.jobs[id].status))).map((b) => b.id);
  await Promise.all(
    ids.map(async (id) => {
      try {
        (await api.batch(id)).jobs.forEach((j) => useStudio.getState().upsertJob(j));
      } catch {
        /* next tick */
      }
    }),
  );
}

/** SSE subscription + safety poll + beforeunload guard. Mount once. */
export function useLiveSync(): void {
  useEffect(() => {
    const stop = connectEvents(
      (e) => applyEvent(e.event, e.data),
      () => void resyncActive(),
      (c) => useStudio.getState().setSse(c),
    );
    const timer = setInterval(() => {
      const s = useStudio.getState();
      if (hasRunning(s.jobs)) void resyncActive(); // safety net: also covers missed SSE events
    }, 5000);
    return () => {
      stop();
      clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    const h = (e: BeforeUnloadEvent) => {
      const s = useStudio.getState();
      if (hasRunning(s.jobs) || unsavedAssetIds(s.jobs, s.downloaded).length > 0) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, []);
}
