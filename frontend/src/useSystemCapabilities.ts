import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchSystemCapabilities,
  type SystemCapabilities,
} from "./systemCapabilities";

export type SystemCapabilitiesLoadState =
  | { readonly status: "loading" }
  | { readonly status: "success"; readonly data: SystemCapabilities }
  | {
      readonly status: "error";
      readonly error: Error;
      readonly isRetrying: boolean;
    };

export interface UseSystemCapabilitiesResult {
  readonly state: SystemCapabilitiesLoadState;
  readonly reload: () => void;
}

function normalizeError(error: unknown): Error {
  if (error instanceof Error) {
    return error;
  }

  return new Error("读取 V2 能力状态失败：请求抛出了非标准错误。请检查浏览器控制台和后端日志。");
}

export function useSystemCapabilities(): UseSystemCapabilitiesResult {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<SystemCapabilitiesLoadState>({ status: "loading" });
  const hasError = useRef<boolean>(false);

  useEffect(() => {
    const controller = new AbortController();
    setState((currentState) =>
      hasError.current && currentState.status === "error"
        ? { ...currentState, isRetrying: true }
        : { status: "loading" },
    );

    void fetchSystemCapabilities(controller.signal)
      .then((data) => {
        hasError.current = false;
        setState({ status: "success", data });
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }

        hasError.current = true;
        setState({ status: "error", error: normalizeError(error), isRetrying: false });
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
