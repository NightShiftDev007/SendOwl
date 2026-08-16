import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchMediaTopicTimeline,
  type MediaTopicTimelineQuery,
  type MediaTopicTimelineResponse,
} from "./mediaContracts";

export type MediaTopicTimelineLoadState =
  | { readonly status: "loading" }
  | { readonly status: "success"; readonly data: MediaTopicTimelineResponse }
  | {
      readonly status: "error";
      readonly error: Error;
      readonly isRetrying: boolean;
    };

export interface UseMediaTopicTimelineResult {
  readonly state: MediaTopicTimelineLoadState;
  readonly reload: () => void;
}

function normalizeMediaTopicTimelineError(error: unknown): Error {
  return error instanceof Error
    ? error
    : new Error(
        "读取议题时间线失败：请求抛出了非标准错误。请检查浏览器控制台和后端日志。",
      );
}

export function useMediaTopicTimeline(
  query: MediaTopicTimelineQuery,
): UseMediaTopicTimelineResult {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<MediaTopicTimelineLoadState>({ status: "loading" });
  const hasError = useRef<boolean>(false);

  useEffect(() => {
    const controller = new AbortController();
    setState((currentState) =>
      hasError.current && currentState.status === "error"
        ? { ...currentState, isRetrying: true }
        : { status: "loading" },
    );

    void fetchMediaTopicTimeline(query, controller.signal)
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
          error: normalizeMediaTopicTimelineError(error),
          isRetrying: false,
        });
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
