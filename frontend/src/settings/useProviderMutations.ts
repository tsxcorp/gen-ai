import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ProviderId, ProviderInput } from "../api/types";

/** save/test/delete for one provider; refreshes providers + manifests (`configured`) after save/delete. */
export function useProviderMutations(id: ProviderId, buildPayload: () => ProviderInput, afterSave: () => void, afterDelete: () => void) {
  const qc = useQueryClient();
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["providers"] });
    void qc.invalidateQueries({ queryKey: ["manifests"] });
  };
  const save = useMutation<unknown, Error, void>({
    mutationFn: () => api.saveProvider(id, buildPayload()),
    onSuccess: () => {
      afterSave(); // never keep a key in the page after sending it
      refresh();
    },
  });
  const test = useMutation<{ ok?: boolean; message?: string }, Error, void>({ mutationFn: () => api.testProvider(id) });
  const remove = useMutation<unknown, Error, void>({
    mutationFn: () => api.deleteProvider(id),
    onSuccess: () => {
      afterDelete();
      save.reset();
      test.reset();
      refresh();
    },
  });
  return { save, test, remove };
}
