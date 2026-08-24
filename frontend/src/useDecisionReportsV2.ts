import { useCallback, useEffect, useState } from "react";

import {
  fetchDecisionReportsV2,
  type DecisionReportsV2Response,
} from "./decisionReportV2Contracts";

export type DecisionReportsV2LoadState =
  | { readonly status: "loading"; readonly data: DecisionReportsV2Response | null }
  | { readonly status: "success"; readonly data: DecisionReportsV2Response }
  | { readonly status: "error"; readonly error: Error; readonly data: DecisionReportsV2Response | null };

function normalizeError(error: unknown): Error {
  return error instanceof Error
    ? error
    : new Error("读取 DecisionReport V2 失败：请求抛出了非标准错误。");
}

export function useDecisionReportsV2(): {
  readonly state: DecisionReportsV2LoadState;
  readonly reload: () => void;
} {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<DecisionReportsV2LoadState>({
    status: "loading",
    data: null,
  });

  useEffect(() => {
    const controller = new AbortController();
    setState((current) => ({ status: "loading", data: current.data }));
    void fetchDecisionReportsV2(controller.signal)
      .then((data) => setState({ status: "success", data }))
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setState((current) => ({
            status: "error",
            error: normalizeError(error),
            data: current.data,
          }));
        }
      });
    return () => controller.abort();
  }, [requestVersion]);

  return {
    state,
    reload: useCallback((): void => setRequestVersion((current) => current + 1), []),
  };
}
