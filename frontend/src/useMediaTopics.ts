import { useCallback, useEffect, useRef, useState } from "react";

import { fetchMediaTopics, type MediaTopicsResponse } from "./mediaContracts";

export type MediaTopicsLoadState =
  | { readonly status: "loading"; readonly data: MediaTopicsResponse | null }
  | { readonly status: "success"; readonly data: MediaTopicsResponse }
  | {
      readonly status: "error";
      readonly error: Error;
      readonly isRetrying: boolean;
      readonly data: MediaTopicsResponse | null;
    };

export interface UseMediaTopicsResult {
  readonly state: MediaTopicsLoadState;
  readonly reload: () => void;
}

function currentData(state: MediaTopicsLoadState): MediaTopicsResponse | null {
  return state.data;
}

function normalizeMediaTopicsError(error: unknown): Error {
  return error instanceof Error
    ? error
    : new Error(
        "读取完整议题目录失败：请求抛出了非标准错误。请检查浏览器控制台和后端日志。",
      );
}

export function useMediaTopics(page: number, pageSize: number): UseMediaTopicsResult {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<MediaTopicsLoadState>({
    status: "loading",
    data: null,
  });
  const hasError = useRef<boolean>(false);

  useEffect(() => {
    const controller = new AbortController();

    setState((currentState) =>
      hasError.current && currentState.status === "error"
        ? { ...currentState, isRetrying: true }
        : { status: "loading", data: currentData(currentState) },
    );

    void fetchMediaTopics(page, pageSize, controller.signal)
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
          error: normalizeMediaTopicsError(error),
          isRetrying: false,
          data: currentData(currentState),
        }));
      });

    return () => {
      controller.abort();
    };
  }, [page, pageSize, requestVersion]);

  const reload = useCallback((): void => {
    setRequestVersion((currentVersion) => currentVersion + 1);
  }, []);

  return { state, reload };
}
