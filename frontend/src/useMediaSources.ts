import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchMediaSources,
  type MediaSourcesResponse,
} from "./mediaSourceContracts";

export type MediaSourcesLoadState =
  | { readonly status: "loading" }
  | { readonly status: "success"; readonly data: MediaSourcesResponse }
  | {
      readonly status: "error";
      readonly error: Error;
      readonly isRetrying: boolean;
    };

export interface UseMediaSourcesResult {
  readonly state: MediaSourcesLoadState;
  readonly reload: () => void;
}

function normalizeMediaSourcesError(error: unknown): Error {
  return error instanceof Error
    ? error
    : new Error(
        "读取媒体源健康状态失败：请求抛出了非标准错误。请检查浏览器控制台和后端日志。",
      );
}

export function useMediaSources(): UseMediaSourcesResult {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<MediaSourcesLoadState>({ status: "loading" });
  const hasError = useRef<boolean>(false);

  useEffect(() => {
    const controller = new AbortController();
    setState((currentState) =>
      hasError.current && currentState.status === "error"
        ? { ...currentState, isRetrying: true }
        : { status: "loading" },
    );

    void fetchMediaSources(controller.signal)
      .then((data) => {
        hasError.current = false;
        setState({ status: "success", data });
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }

        hasError.current = true;
        setState({
          status: "error",
          error: normalizeMediaSourcesError(error),
          isRetrying: false,
        });
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
