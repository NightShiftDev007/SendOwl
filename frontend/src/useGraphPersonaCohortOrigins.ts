import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchGraphPersonaCohortOrigins,
  type GraphPersonaCohortOriginsResponse,
} from "./worldModelContracts";

export type GraphPersonaCohortOriginsLoadState =
  | { readonly status: "idle" }
  | { readonly status: "loading"; readonly data: GraphPersonaCohortOriginsResponse | null }
  | { readonly status: "success"; readonly data: GraphPersonaCohortOriginsResponse }
  | {
      readonly status: "error";
      readonly error: Error;
      readonly isRetrying: boolean;
      readonly data: GraphPersonaCohortOriginsResponse | null;
    };

interface UseGraphPersonaCohortOriginsResult {
  readonly state: GraphPersonaCohortOriginsLoadState;
  readonly reload: () => void;
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function currentData(
  state: GraphPersonaCohortOriginsLoadState,
): GraphPersonaCohortOriginsResponse | null {
  return state.status === "idle" ? null : state.data;
}

export function useGraphPersonaCohortOrigins(
  cohortId: string | null,
  page: number,
  pageSize: number,
): UseGraphPersonaCohortOriginsResult {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<GraphPersonaCohortOriginsLoadState>({ status: "idle" });
  const hasError = useRef<boolean>(false);
  const previousKey = useRef<string | null>(null);

  useEffect(() => {
    if (cohortId === null) {
      hasError.current = false;
      previousKey.current = null;
      setState({ status: "idle" });
      return;
    }
    const requestKey = `${cohortId}:${page}:${pageSize}`;
    const isNewRequest = previousKey.current !== requestKey;
    if (isNewRequest) {
      hasError.current = false;
      previousKey.current = requestKey;
    }
    const controller = new AbortController();
    setState((current) => hasError.current && current.status === "error"
      ? { ...current, isRetrying: true }
      : { status: "loading", data: isNewRequest ? null : currentData(current) });
    void fetchGraphPersonaCohortOrigins(cohortId, page, pageSize, controller.signal)
      .then((data) => {
        hasError.current = false;
        setState({ status: "success", data });
      })
      .catch((error: unknown) => {
        if (isAbortError(error)) return;
        hasError.current = true;
        setState((current) => ({
          status: "error",
          error: error instanceof Error
            ? error
            : new Error("读取图谱 Persona 来源失败：请求抛出了非标准错误。"),
          isRetrying: false,
          data: currentData(current),
        }));
      });
    return () => controller.abort();
  }, [cohortId, page, pageSize, requestVersion]);

  const reload = useCallback((): void => {
    setRequestVersion((current) => current + 1);
  }, []);
  return { state, reload };
}
