import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchMediaArticles,
  type MediaArticlesQuery,
  type MediaArticlesResponse,
} from "./mediaContracts";

export type MediaArticlesLoadState =
  | { readonly status: "loading"; readonly data: MediaArticlesResponse | null }
  | { readonly status: "success"; readonly data: MediaArticlesResponse }
  | {
      readonly status: "error";
      readonly error: Error;
      readonly isRetrying: boolean;
      readonly data: MediaArticlesResponse | null;
    };

export interface UseMediaArticlesResult {
  readonly state: MediaArticlesLoadState;
  readonly reload: () => void;
}

function previousArticlesData(state: MediaArticlesLoadState): MediaArticlesResponse | null {
  return state.data;
}

function normalizeMediaArticlesError(error: unknown): Error {
  return error instanceof Error
    ? error
    : new Error("读取媒体报道失败：请求抛出了非标准错误。请检查浏览器控制台和后端日志。");
}

export function useMediaArticles(query: MediaArticlesQuery): UseMediaArticlesResult {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<MediaArticlesLoadState>({
    status: "loading",
    data: null,
  });
  const hasError = useRef<boolean>(false);

  useEffect(() => {
    const controller = new AbortController();
    setState((currentState) =>
      hasError.current && currentState.status === "error"
        ? { ...currentState, isRetrying: true }
        : { status: "loading", data: previousArticlesData(currentState) },
    );

    void fetchMediaArticles(query, controller.signal)
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
          error: normalizeMediaArticlesError(error),
          isRetrying: false,
          data: previousArticlesData(currentState),
        }));
      });

    return () => {
      controller.abort();
    };
  }, [query, requestVersion]);

  const reload = useCallback((): void => {
    setRequestVersion((currentVersion) => currentVersion + 1);
  }, []);

  return { state, reload };
}
