import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchSemanticExperimentComparison,
  fetchSemanticExperimentDetail,
  fetchSemanticExperiments,
  fetchSemanticReadiness,
  fetchSemanticTrialEvents,
  type SemanticExperimentComparison,
  type SemanticExperimentDetail,
  type SemanticExperimentsResponse,
  type SemanticReadiness,
  type SemanticTrialEvent,
} from "./semanticExperimentContracts";

export type SemanticReadinessLoadState =
  | { readonly status: "loading"; readonly data: SemanticReadiness | null }
  | { readonly status: "success"; readonly data: SemanticReadiness }
  | { readonly status: "error"; readonly error: Error; readonly data: SemanticReadiness | null };

export type SemanticExperimentsLoadState =
  | { readonly status: "loading"; readonly data: SemanticExperimentsResponse | null }
  | { readonly status: "success"; readonly data: SemanticExperimentsResponse }
  | { readonly status: "error"; readonly error: Error; readonly data: SemanticExperimentsResponse | null };

export type SemanticExperimentDetailLoadState =
  | { readonly status: "idle" }
  | { readonly status: "loading"; readonly data: SemanticExperimentDetail | null; readonly isPolling: boolean }
  | { readonly status: "success"; readonly data: SemanticExperimentDetail }
  | { readonly status: "error"; readonly error: Error; readonly data: SemanticExperimentDetail | null };

export type SemanticComparisonLoadState =
  | { readonly status: "idle" }
  | { readonly status: "loading"; readonly data: SemanticExperimentComparison | null }
  | { readonly status: "success"; readonly data: SemanticExperimentComparison }
  | { readonly status: "error"; readonly error: Error; readonly data: SemanticExperimentComparison | null };

export type SemanticEventsLoadState =
  | { readonly status: "idle" }
  | { readonly status: "loading"; readonly items: readonly SemanticTrialEvent[]; readonly isPolling: boolean }
  | { readonly status: "success"; readonly items: readonly SemanticTrialEvent[] }
  | { readonly status: "error"; readonly error: Error; readonly items: readonly SemanticTrialEvent[] };

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function normalizeError(error: unknown, operation: string): Error {
  return error instanceof Error
    ? error
    : new Error(`${operation}失败：请求抛出了非标准错误。请检查后端日志。`);
}

function isTerminal(status: SemanticExperimentDetail["status"]): boolean {
  return status === "succeeded" || status === "failed";
}

export function useSemanticReadiness(): {
  readonly state: SemanticReadinessLoadState;
  readonly reload: () => void;
} {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<SemanticReadinessLoadState>({ status: "loading", data: null });

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof globalThis.setTimeout> | null = null;

    setState((current) => ({
      status: "loading",
      data: current.status === "loading" ? current.data : current.data,
    }));

    void fetchSemanticReadiness(controller.signal)
      .then((data) => {
        setState({ status: "success", data });
        timer = globalThis.setTimeout(() => {
          setRequestVersion((current) => current + 1);
        }, 10_000);
      })
      .catch((error: unknown) => {
        if (isAbortError(error)) {
          return;
        }

        setState((current) => ({
          status: "error",
          error: normalizeError(error, "读取语义运行就绪状态"),
          data: current.status === "loading" ? current.data : current.data,
        }));
        timer = globalThis.setTimeout(() => {
          setRequestVersion((current) => current + 1);
        }, 10_000);
      });

    return () => {
      controller.abort();
      if (timer !== null) {
        globalThis.clearTimeout(timer);
      }
    };
  }, [requestVersion]);

  return {
    state,
    reload: useCallback((): void => {
      setRequestVersion((current) => current + 1);
    }, []),
  };
}

export function useSemanticExperiments(): {
  readonly state: SemanticExperimentsLoadState;
  readonly reload: () => void;
} {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<SemanticExperimentsLoadState>({ status: "loading", data: null });

  useEffect(() => {
    const controller = new AbortController();
    setState((current) => ({ status: "loading", data: current.data }));

    void fetchSemanticExperiments(controller.signal)
      .then((data) => setState({ status: "success", data }))
      .catch((error: unknown) => {
        if (!isAbortError(error)) {
          setState((current) => ({
            status: "error",
            error: normalizeError(error, "读取语义实验目录"),
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

export function useSemanticExperimentDetail(
  experimentId: string | null,
): {
  readonly state: SemanticExperimentDetailLoadState;
  readonly reload: () => void;
} {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<SemanticExperimentDetailLoadState>({ status: "idle" });
  const previousId = useRef<string | null>(null);

  useEffect(() => {
    if (experimentId === null) {
      previousId.current = null;
      setState({ status: "idle" });
      return;
    }

    const controller = new AbortController();
    let timer: ReturnType<typeof globalThis.setTimeout> | null = null;
    const isNewExperiment = previousId.current !== experimentId;
    previousId.current = experimentId;

    setState((current) => ({
      status: "loading",
      data: !isNewExperiment && current.status !== "idle" ? current.data : null,
      isPolling: !isNewExperiment,
    }));

    void fetchSemanticExperimentDetail(experimentId, controller.signal)
      .then((data) => {
        setState({ status: "success", data });
        if (!isTerminal(data.status)) {
          timer = globalThis.setTimeout(() => {
            setRequestVersion((current) => current + 1);
          }, 2_000);
        }
      })
      .catch((error: unknown) => {
        if (!isAbortError(error)) {
          setState((current) => ({
            status: "error",
            error: normalizeError(error, "读取语义实验详情"),
            data: current.status === "idle" ? null : current.data,
          }));
        }
      });

    return () => {
      controller.abort();
      if (timer !== null) {
        globalThis.clearTimeout(timer);
      }
    };
  }, [experimentId, requestVersion]);

  return {
    state,
    reload: useCallback((): void => setRequestVersion((current) => current + 1), []),
  };
}

export function useSemanticComparison(
  experimentId: string | null,
): {
  readonly state: SemanticComparisonLoadState;
  readonly reload: () => void;
} {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<SemanticComparisonLoadState>({ status: "idle" });

  useEffect(() => {
    if (experimentId === null) {
      setState({ status: "idle" });
      return;
    }

    const controller = new AbortController();
    setState((current) => ({
      status: "loading",
      data: current.status === "idle" ? null : current.data,
    }));

    void fetchSemanticExperimentComparison(experimentId, controller.signal)
      .then((data) => setState({ status: "success", data }))
      .catch((error: unknown) => {
        if (!isAbortError(error)) {
          setState((current) => ({
            status: "error",
            error: normalizeError(error, "读取语义实验计数比较"),
            data: current.status === "idle" ? null : current.data,
          }));
        }
      });

    return () => controller.abort();
  }, [experimentId, requestVersion]);

  return {
    state,
    reload: useCallback((): void => setRequestVersion((current) => current + 1), []),
  };
}

export function useSemanticTrialEvents(
  trialId: string | null,
  trialStatus: "queued" | "running" | "succeeded" | "failed" | null,
): {
  readonly state: SemanticEventsLoadState;
  readonly reload: () => void;
} {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<SemanticEventsLoadState>({ status: "idle" });
  const cursor = useRef<number>(0);
  const previousTrialId = useRef<string | null>(null);

  useEffect(() => {
    if (trialId === null) {
      previousTrialId.current = null;
      cursor.current = 0;
      setState({ status: "idle" });
      return;
    }

    const isNewTrial = previousTrialId.current !== trialId;
    if (isNewTrial) {
      previousTrialId.current = trialId;
      cursor.current = 0;
    }

    const controller = new AbortController();
    let timer: ReturnType<typeof globalThis.setTimeout> | null = null;

    setState((current) => ({
      status: "loading",
      items: isNewTrial || current.status === "idle" ? [] : current.items,
      isPolling: !isNewTrial,
    }));

    const requestCursor = cursor.current;
    void fetchSemanticTrialEvents(trialId, requestCursor, controller.signal)
      .then((page) => {
        if (page.trial_id !== trialId || page.after_sequence !== requestCursor) {
          throw new Error("事件页不属于当前 Trial 或游标不匹配；已停止合并。 ");
        }

        cursor.current = page.next_after_sequence;
        setState((current) => ({
          status: "success",
          items: [
            ...(isNewTrial || current.status === "idle" ? [] : current.items),
            ...page.items,
          ],
        }));

        if (page.has_more || trialStatus === "running") {
          timer = globalThis.setTimeout(() => {
            setRequestVersion((current) => current + 1);
          }, page.has_more ? 0 : 1_500);
        }
      })
      .catch((error: unknown) => {
        if (!isAbortError(error)) {
          setState((current) => ({
            status: "error",
            error: normalizeError(error, "读取 Trial 事件"),
            items: current.status === "idle" ? [] : current.items,
          }));
        }
      });

    return () => {
      controller.abort();
      if (timer !== null) {
        globalThis.clearTimeout(timer);
      }
    };
  }, [requestVersion, trialId, trialStatus]);

  return {
    state,
    reload: useCallback((): void => setRequestVersion((current) => current + 1), []),
  };
}
