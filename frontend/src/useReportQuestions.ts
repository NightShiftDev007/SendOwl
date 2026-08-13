import { useCallback, useEffect, useState } from "react";

import {
  fetchReportQuestions,
  type ReportQuestionsResponse,
} from "./reportQuestionContracts";

type ReportQuestionsLoadState =
  | { readonly status: "idle"; readonly data: null }
  | { readonly status: "loading"; readonly data: ReportQuestionsResponse | null }
  | { readonly status: "success"; readonly data: ReportQuestionsResponse }
  | { readonly status: "error"; readonly error: Error; readonly data: ReportQuestionsResponse | null };

function normalizeError(error: unknown): Error {
  return error instanceof Error
    ? error
    : new Error("读取证据追问失败：请求抛出了非标准错误。");
}

export function useReportQuestions(reportId: string | null): {
  readonly state: ReportQuestionsLoadState;
  readonly reload: () => void;
} {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<ReportQuestionsLoadState>({ status: "idle", data: null });

  useEffect(() => {
    if (reportId === null) {
      setState({ status: "idle", data: null });
      return undefined;
    }
    const controller = new AbortController();
    let pollId: number | null = null;
    const load = (): void => {
      setState((current) => ({ status: "loading", data: current.data }));
      void fetchReportQuestions(reportId, controller.signal)
        .then((data) => {
          setState({ status: "success", data });
          if (data.items.some((item) => item.status === "queued" || item.status === "running")) {
            pollId = globalThis.setTimeout(load, 2_000);
          }
        })
        .catch((error: unknown) => {
          if (!(error instanceof DOMException && error.name === "AbortError")) {
            setState((current) => ({
              status: "error",
              error: normalizeError(error),
              data: current.data,
            }));
          }
        });
    };
    load();
    return () => {
      controller.abort();
      if (pollId !== null) {
        globalThis.clearTimeout(pollId);
      }
    };
  }, [reportId, requestVersion]);

  return {
    state,
    reload: useCallback((): void => setRequestVersion((current) => current + 1), []),
  };
}
