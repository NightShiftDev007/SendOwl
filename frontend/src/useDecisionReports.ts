import { useCallback, useEffect, useState } from "react";

import {
  fetchDecisionReports,
  type DecisionReportsResponse,
} from "./decisionReportContracts";

export type DecisionReportsLoadState =
  | { readonly status: "loading"; readonly data: DecisionReportsResponse | null }
  | { readonly status: "success"; readonly data: DecisionReportsResponse }
  | { readonly status: "error"; readonly error: Error; readonly data: DecisionReportsResponse | null };

function normalizeError(error: unknown): Error {
  return error instanceof Error
    ? error
    : new Error("读取持久报告失败：请求抛出了非标准错误。");
}

export function useDecisionReports(): {
  readonly state: DecisionReportsLoadState;
  readonly reload: () => void;
} {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<DecisionReportsLoadState>({ status: "loading", data: null });

  useEffect(() => {
    const controller = new AbortController();
    setState((current) => ({ status: "loading", data: current.data }));
    void fetchDecisionReports(controller.signal)
      .then((data) => setState({ status: "success", data }))
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          setState((current) => ({ status: "error", error: normalizeError(error), data: current.data }));
        }
      });
    return () => controller.abort();
  }, [requestVersion]);

  return {
    state,
    reload: useCallback((): void => setRequestVersion((current) => current + 1), []),
  };
}
