import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchMediaSyncStatus,
  type MediaSyncStatusResponse,
} from "./mediaSyncContracts";

const refreshIntervalMilliseconds = 60_000;

export type MediaSyncStatusLoadState =
  | { readonly status: "loading"; readonly data: MediaSyncStatusResponse | null }
  | { readonly status: "success"; readonly data: MediaSyncStatusResponse }
  | {
      readonly status: "error";
      readonly error: Error;
      readonly isRetrying: boolean;
      readonly data: MediaSyncStatusResponse | null;
    };

export interface UseMediaSyncStatusResult {
  readonly state: MediaSyncStatusLoadState;
  readonly reload: () => void;
}

function stateData(state: MediaSyncStatusLoadState): MediaSyncStatusResponse | null {
  return state.data;
}

function normalizeMediaSyncStatusError(error: unknown): Error {
  return error instanceof Error
    ? error
    : new Error(
        "读取媒体同步状态失败：请求抛出了非标准错误。请检查浏览器控制台和后端日志。",
      );
}

export function useMediaSyncStatus(): UseMediaSyncStatusResult {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<MediaSyncStatusLoadState>({
    status: "loading",
    data: null,
  });
  const hasError = useRef<boolean>(false);

  useEffect(() => {
    const controller = new AbortController();

    setState((currentState) =>
      hasError.current && currentState.status === "error"
        ? { ...currentState, isRetrying: true }
        : { status: "loading", data: stateData(currentState) },
    );

    void fetchMediaSyncStatus(controller.signal)
      .then((data) => {
        hasError.current = false;
        setState({ status: "success", data });
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }

        hasError.current = true;
        setState((currentState) => ({
          status: "error",
          error: normalizeMediaSyncStatusError(error),
          isRetrying: false,
          data: stateData(currentState),
        }));
      });

    return () => {
      controller.abort();
    };
  }, [requestVersion]);

  const isRequesting = state.status === "loading"
    || (state.status === "error" && state.isRetrying);

  useEffect(() => {
    if (isRequesting || document.visibilityState !== "visible") {
      return;
    }

    const refreshTimer = globalThis.setTimeout(() => {
      if (document.visibilityState === "visible") {
        setRequestVersion((currentVersion) => currentVersion + 1);
      }
    }, refreshIntervalMilliseconds);

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
