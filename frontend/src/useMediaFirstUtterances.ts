import { useCallback, useEffect, useState } from "react";

import {
  fetchMediaFirstUtterances,
  type MediaFirstUtterancesResponse,
} from "./mediaContracts";

export type MediaFirstUtterancesState =
  | { readonly status: "loading" }
  | { readonly status: "success"; readonly data: MediaFirstUtterancesResponse }
  | { readonly status: "error"; readonly error: Error; readonly isRetrying: boolean };

export function useMediaFirstUtterances(
  topicId: string,
  limit: number,
): { readonly state: MediaFirstUtterancesState; readonly reload: () => void } {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<MediaFirstUtterancesState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });
    void fetchMediaFirstUtterances(topicId, limit, controller.signal)
      .then((data) => setState({ status: "success", data }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }
        setState({
          status: "error",
          error: error instanceof Error ? error : new Error("读取首发证据时收到非标准错误。"),
          isRetrying: false,
        });
      });
    return () => controller.abort();
  }, [limit, requestVersion, topicId]);

  const reload = useCallback((): void => {
    setState((current) =>
      current.status === "error" ? { ...current, isRetrying: true } : current,
    );
    setRequestVersion((current) => current + 1);
  }, []);

  return { state, reload };
}
