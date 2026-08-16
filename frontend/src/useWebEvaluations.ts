import { useCallback, useEffect, useState } from "react";

import {
  fetchWebEvaluation,
  fetchWebEvaluations,
  fetchWebReadiness,
  fetchWebTasks,
  fetchWebTrial,
  type WebEvaluationDetail,
  type WebEvaluationSummary,
  type WebReadiness,
  type WebTask,
  type WebTrial,
} from "./webEvaluationContracts";

type LoadState<T> =
  | { readonly status: "loading"; readonly data: T | null }
  | { readonly status: "success"; readonly data: T }
  | { readonly status: "error"; readonly error: Error; readonly data: T | null };

export type WebReadinessLoadState = LoadState<WebReadiness>;

function normalizeError(error: unknown, operation: string): Error {
  return error instanceof Error ? error : new Error(`${operation}失败：请求抛出了非标准错误。`);
}

function useResource<T>(
  loader: (signal: AbortSignal) => Promise<T>,
  refreshMilliseconds: number | null,
  shouldRefresh: ((data: T) => boolean) | null,
): { readonly state: LoadState<T>; readonly reload: () => void } {
  const [version, setVersion] = useState(0);
  const [state, setState] = useState<LoadState<T>>({ status: "loading", data: null });
  useEffect(() => {
    const controller = new AbortController();
    setState((current) => ({ status: "loading", data: current.data }));
    void loader(controller.signal)
      .then((data) => setState({ status: "success", data }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState((current) => ({ status: "error", error: normalizeError(error, "读取 Web 资源"), data: current.data }));
      });
    return () => {
      controller.abort();
    };
  }, [loader, version]);
  useEffect(() => {
    if (
      refreshMilliseconds === null
      || state.status !== "success"
      || (shouldRefresh !== null && !shouldRefresh(state.data))
    ) {
      return undefined;
    }
    const interval = window.setInterval(
      () => setVersion((current) => current + 1),
      refreshMilliseconds,
    );
    return () => window.clearInterval(interval);
  }, [refreshMilliseconds, shouldRefresh, state]);
  return { state, reload: useCallback(() => setVersion((current) => current + 1), []) };
}

export function useWebReadiness(): ReturnType<typeof useResource<WebReadiness>> {
  const loader = useCallback((signal: AbortSignal) => fetchWebReadiness(signal), []);
  const shouldRefresh = useCallback((_data: WebReadiness) => true, []);
  return useResource(loader, 10_000, shouldRefresh);
}

export function useWebTasks(): ReturnType<typeof useResource<readonly WebTask[]>> {
  const loader = useCallback(async (signal: AbortSignal) => (await fetchWebTasks(signal)).items, []);
  return useResource(loader, null, null);
}

export function useWebEvaluations(page: number): ReturnType<typeof useResource<{ readonly items: readonly WebEvaluationSummary[]; readonly total: number }>> {
  const loader = useCallback(async (signal: AbortSignal) => {
    const response = await fetchWebEvaluations(page, signal);
    return { items: response.items, total: response.total };
  }, [page]);
  return useResource(loader, null, null);
}

export function useWebEvaluation(id: string | null): ReturnType<typeof useResource<WebEvaluationDetail | null>> {
  const loader = useCallback((signal: AbortSignal) => id === null ? Promise.resolve(null) : fetchWebEvaluation(id, signal), [id]);
  const shouldRefresh = useCallback(
    (data: WebEvaluationDetail | null) => data !== null && (data.status === "queued" || data.status === "running"),
    [],
  );
  return useResource(loader, id === null ? null : 2_000, shouldRefresh);
}

export function useWebTrial(id: string | null): ReturnType<typeof useResource<WebTrial | null>> {
  const loader = useCallback((signal: AbortSignal) => id === null ? Promise.resolve(null) : fetchWebTrial(id, signal), [id]);
  const shouldRefresh = useCallback(
    (data: WebTrial | null) => data !== null && (data.status === "queued" || data.status === "running"),
    [],
  );
  return useResource(loader, id === null ? null : 2_000, shouldRefresh);
}
