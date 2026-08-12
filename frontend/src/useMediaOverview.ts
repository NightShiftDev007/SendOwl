import { useCallback, useEffect, useRef, useState } from "react";

import { fetchMediaOverview, type MediaOverview } from "./mediaContracts";

export type MediaOverviewLoadState =
  | { readonly status: "loading" }
  | { readonly status: "success"; readonly data: MediaOverview }
  | {
      readonly status: "error";
      readonly error: Error;
      readonly isRetrying: boolean;
    };

export interface UseMediaOverviewResult {
  readonly state: MediaOverviewLoadState;
  readonly reload: () => void;
}

function normalizeMediaOverviewError(error: unknown): Error {
  return error instanceof Error
    ? error
    : new Error("读取媒体态势失败：请求抛出了非标准错误。请检查浏览器控制台和后端日志。");
}

export function useMediaOverview(): UseMediaOverviewResult {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<MediaOverviewLoadState>({ status: "loading" });
  const hasError = useRef<boolean>(false);

  useEffect(() => {
    const controller = new AbortController();
    setState((currentState) =>
      hasError.current && currentState.status === "error"
        ? { ...currentState, isRetrying: true }
        : { status: "loading" },
    );

    void fetchMediaOverview(controller.signal)
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
          error: normalizeMediaOverviewError(error),
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
