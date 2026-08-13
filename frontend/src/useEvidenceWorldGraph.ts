import { useCallback, useEffect, useState } from "react";

import {
  fetchEvidenceWorldGraph,
  type EvidenceWorldGraph,
} from "./worldModelContracts";

export type EvidenceWorldGraphState =
  | { readonly status: "loading" }
  | { readonly status: "success"; readonly data: EvidenceWorldGraph }
  | { readonly status: "error"; readonly error: Error; readonly isRetrying: boolean };

export function useEvidenceWorldGraph(
  worldModelId: string,
  snapshotId: string,
): { readonly state: EvidenceWorldGraphState; readonly reload: () => void } {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<EvidenceWorldGraphState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    setState((current) => current.status === "error"
      ? { ...current, isRetrying: true }
      : { status: "loading" });
    void fetchEvidenceWorldGraph(worldModelId, snapshotId, controller.signal)
      .then((data) => setState({ status: "success", data }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }
        setState({
          status: "error",
          error: error instanceof Error ? error : new Error("证据世界图请求抛出了非标准错误。"),
          isRetrying: false,
        });
      });
    return () => controller.abort();
  }, [requestVersion, snapshotId, worldModelId]);

  const reload = useCallback((): void => {
    setRequestVersion((current) => current + 1);
  }, []);
  return { state, reload };
}
