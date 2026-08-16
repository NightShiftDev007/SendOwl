import { useCallback, useEffect, useState } from "react";

import { fetchMediaSourceEvidence, type MediaSourceEvidenceResponse } from "./mediaSourceContracts";

export type MediaSourceEvidenceState =
  | { readonly status: "idle" }
  | { readonly status: "loading" }
  | { readonly status: "success"; readonly data: MediaSourceEvidenceResponse }
  | { readonly status: "error"; readonly error: Error };

export interface UseMediaSourceEvidenceResult {
  readonly state: MediaSourceEvidenceState;
  readonly reload: () => void;
}

export function useMediaSourceEvidence(
  sourceId: string | null,
  page: number,
): UseMediaSourceEvidenceResult {
  const [state, setState] = useState<MediaSourceEvidenceState>({ status: "idle" });
  const [requestVersion, setRequestVersion] = useState<number>(0);

  useEffect(() => {
    if (sourceId === null) {
      setState({ status: "idle" });
      return undefined;
    }
    const controller = new AbortController();
    setState({ status: "loading" });
    void fetchMediaSourceEvidence(sourceId, page, 20, controller.signal)
      .then((data) => setState({ status: "success", data }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState({ status: "error", error: error instanceof Error ? error : new Error("读取来源档案失败。") });
      });
    return () => controller.abort();
  }, [page, requestVersion, sourceId]);

  const reload = useCallback((): void => {
    setRequestVersion((currentVersion) => currentVersion + 1);
  }, []);

  return { state, reload };
}
