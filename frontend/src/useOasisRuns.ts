import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchOasisReadiness,
  fetchPlatformSmokeRunDetail,
  fetchPlatformSmokeRuns,
  type OasisReadiness,
  type PlatformSmokeRunDetail,
  type PlatformSmokeRunsResponse,
} from "./oasisContracts";

const runPollingIntervalMilliseconds = 1_500;
const readinessRefreshIntervalMilliseconds = 10_000;

export type OasisReadinessLoadState =
  | { readonly status: "loading"; readonly data: OasisReadiness | null }
  | { readonly status: "success"; readonly data: OasisReadiness }
  | {
      readonly status: "error";
      readonly error: Error;
      readonly isRetrying: boolean;
      readonly data: OasisReadiness | null;
    };

export type PlatformSmokeRunsLoadState =
  | { readonly status: "loading"; readonly data: PlatformSmokeRunsResponse | null }
  | { readonly status: "success"; readonly data: PlatformSmokeRunsResponse }
  | {
      readonly status: "error";
      readonly error: Error;
      readonly isRetrying: boolean;
      readonly data: PlatformSmokeRunsResponse | null;
    };

export type PlatformSmokeRunDetailLoadState =
  | { readonly status: "idle" }
  | {
      readonly status: "loading";
      readonly data: PlatformSmokeRunDetail | null;
      readonly isPolling: boolean;
    }
  | { readonly status: "success"; readonly data: PlatformSmokeRunDetail }
  | {
      readonly status: "error";
      readonly error: Error;
      readonly isRetrying: boolean;
      readonly data: PlatformSmokeRunDetail | null;
    };

export interface UseOasisReadinessResult {
  readonly state: OasisReadinessLoadState;
  readonly reload: () => void;
}

export interface UsePlatformSmokeRunsResult {
  readonly state: PlatformSmokeRunsLoadState;
  readonly reload: () => void;
}

export interface UsePlatformSmokeRunDetailResult {
  readonly state: PlatformSmokeRunDetailLoadState;
  readonly reload: () => void;
}

function normalizeReadinessError(error: unknown): Error {
  return error instanceof Error
    ? error
    : new Error("读取 OASIS 就绪状态失败：请求抛出了非标准错误。请检查后端日志。");
}

function normalizeRunsError(error: unknown): Error {
  return error instanceof Error
    ? error
    : new Error("读取 OASIS 运行目录失败：请求抛出了非标准错误。请检查后端日志。");
}

function normalizeRunDetailError(error: unknown): Error {
  return error instanceof Error
    ? error
    : new Error("读取 OASIS 运行详情失败：请求抛出了非标准错误。请检查后端日志。");
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function readinessData(state: OasisReadinessLoadState): OasisReadiness | null {
  return state.data;
}

function runsData(
  state: PlatformSmokeRunsLoadState,
): PlatformSmokeRunsResponse | null {
  return state.data;
}

function runDetailData(
  state: PlatformSmokeRunDetailLoadState,
  runId: string,
): PlatformSmokeRunDetail | null {
  if (state.status === "idle" || state.data === null) {
    return null;
  }

  return state.data.id === runId ? state.data : null;
}

export function useOasisReadiness(): UseOasisReadinessResult {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<OasisReadinessLoadState>({
    status: "loading",
    data: null,
  });
  const hasError = useRef<boolean>(false);

  useEffect(() => {
    const controller = new AbortController();

    setState((currentState) =>
      hasError.current && currentState.status === "error"
        ? { ...currentState, isRetrying: true }
        : { status: "loading", data: readinessData(currentState) },
    );

    void fetchOasisReadiness(controller.signal)
      .then((data) => {
        hasError.current = false;
        setState({ status: "success", data });
      })
      .catch((error: unknown) => {
        if (isAbortError(error)) {
          return;
        }

        hasError.current = true;
        setState((currentState) => ({
          status: "error",
          error: normalizeReadinessError(error),
          isRetrying: false,
          data: readinessData(currentState),
        }));
      });

    return () => {
      controller.abort();
    };
  }, [requestVersion]);

  const isRequesting = state.status === "loading"
    || (state.status === "error" && state.isRetrying);

  useEffect(() => {
    if (isRequesting) {
      return;
    }

    const refreshTimer = globalThis.setTimeout(() => {
      if (document.visibilityState === "visible") {
        setRequestVersion((currentVersion) => currentVersion + 1);
      }
    }, readinessRefreshIntervalMilliseconds);

    return () => {
      globalThis.clearTimeout(refreshTimer);
    };
  }, [isRequesting, requestVersion]);

  useEffect(() => {
    const refreshWhenVisible = (): void => {
      if (document.visibilityState === "visible") {
        setRequestVersion((currentVersion) => currentVersion + 1);
      }
    };

    document.addEventListener("visibilitychange", refreshWhenVisible);

    return () => {
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, []);

  const reload = useCallback((): void => {
    setRequestVersion((currentVersion) => currentVersion + 1);
  }, []);

  return { state, reload };
}

export function usePlatformSmokeRuns(): UsePlatformSmokeRunsResult {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<PlatformSmokeRunsLoadState>({
    status: "loading",
    data: null,
  });
  const hasError = useRef<boolean>(false);

  useEffect(() => {
    const controller = new AbortController();

    setState((currentState) =>
      hasError.current && currentState.status === "error"
        ? { ...currentState, isRetrying: true }
        : { status: "loading", data: runsData(currentState) },
    );

    void fetchPlatformSmokeRuns(controller.signal)
      .then((data) => {
        hasError.current = false;
        setState({ status: "success", data });
      })
      .catch((error: unknown) => {
        if (isAbortError(error)) {
          return;
        }

        hasError.current = true;
        setState((currentState) => ({
          status: "error",
          error: normalizeRunsError(error),
          isRetrying: false,
          data: runsData(currentState),
        }));
      });

    return () => {
      controller.abort();
    };
  }, [requestVersion]);

  const reload = useCallback((): void => {
    setRequestVersion((currentVersion) => currentVersion + 1);
  }, []);

  return { state, reload };
}

export function usePlatformSmokeRunDetail(
  runId: string | null,
): UsePlatformSmokeRunDetailResult {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<PlatformSmokeRunDetailLoadState>({
    status: "idle",
  });
  const hasError = useRef<boolean>(false);
  const previousRunId = useRef<string | null>(null);

  useEffect(() => {
    if (runId === null) {
      hasError.current = false;
      previousRunId.current = null;
      setState({ status: "idle" });
      return;
    }

    if (previousRunId.current !== runId) {
      hasError.current = false;
      previousRunId.current = runId;
    }

    const controller = new AbortController();
    let pollingTimer: ReturnType<typeof globalThis.setTimeout> | null = null;
    let isDisposed = false;

    const loadRun = async (isPolling: boolean): Promise<void> => {
      setState((currentState) =>
        hasError.current && currentState.status === "error"
          ? { ...currentState, isRetrying: true }
          : {
              status: "loading",
              data: runDetailData(currentState, runId),
              isPolling,
            },
      );

      try {
        const data = await fetchPlatformSmokeRunDetail(runId, controller.signal);

        if (isDisposed || controller.signal.aborted) {
          return;
        }

        hasError.current = false;
        setState({ status: "success", data });

        if (data.status === "queued" || data.status === "running") {
          pollingTimer = globalThis.setTimeout(() => {
            pollingTimer = null;
            void loadRun(true);
          }, runPollingIntervalMilliseconds);
        }
      } catch (error: unknown) {
        if (isAbortError(error) || isDisposed) {
          return;
        }

        hasError.current = true;
        setState((currentState) => ({
          status: "error",
          error: normalizeRunDetailError(error),
          isRetrying: false,
          data: runDetailData(currentState, runId),
        }));
      }
    };

    void loadRun(false);

    return () => {
      isDisposed = true;
      controller.abort();

      if (pollingTimer !== null) {
        globalThis.clearTimeout(pollingTimer);
      }
    };
  }, [requestVersion, runId]);

  const reload = useCallback((): void => {
    setRequestVersion((currentVersion) => currentVersion + 1);
  }, []);

  return { state, reload };
}
