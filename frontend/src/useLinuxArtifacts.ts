import { useCallback, useEffect, useState } from "react";

import {
  fetchLinuxReadiness,
  fetchLinuxEvaluation,
  fetchLinuxTasks,
  fetchLinuxTrial,
  fetchLinuxTrials,
  type LinuxReadiness,
  type LinuxEvaluation,
  type LinuxTask,
  type LinuxTrial,
} from "./linuxArtifactContracts";

type LoadState<T> =
  | { readonly status: "loading"; readonly data: T | null }
  | { readonly status: "success"; readonly data: T }
  | { readonly status: "error"; readonly error: Error; readonly data: T | null };

function useResource<T>(loader: (signal: AbortSignal) => Promise<T>, poll: boolean): { readonly state: LoadState<T>; readonly reload: () => void } {
  const [version, setVersion] = useState(0);
  const [state, setState] = useState<LoadState<T>>({ status: "loading", data: null });
  useEffect(() => {
    const controller = new AbortController();
    void loader(controller.signal)
      .then((data) => setState({ status: "success", data }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState((current) => ({ status: "error", error: error instanceof Error ? error : new Error("Linux resource request failed"), data: current.data }));
      });
    return () => controller.abort();
  }, [loader, version]);
  useEffect(() => {
    if (!poll) return undefined;
    const timer = window.setInterval(() => setVersion((current) => current + 1), 5_000);
    return () => window.clearInterval(timer);
  }, [poll]);
  return { state, reload: useCallback(() => setVersion((current) => current + 1), []) };
}

export function useLinuxReadiness(): ReturnType<typeof useResource<LinuxReadiness>> {
  return useResource(useCallback((signal: AbortSignal) => fetchLinuxReadiness(signal), []), true);
}

export function useLinuxTasks(): ReturnType<typeof useResource<readonly LinuxTask[]>> {
  return useResource(useCallback((signal: AbortSignal) => fetchLinuxTasks(signal), []), false);
}

export function useLinuxTrials(page: number): ReturnType<typeof useResource<Awaited<ReturnType<typeof fetchLinuxTrials>>>> {
  return useResource(useCallback((signal: AbortSignal) => fetchLinuxTrials(page, signal), [page]), false);
}

export function useLinuxTrial(id: string | null): ReturnType<typeof useResource<LinuxTrial | null>> {
  return useResource(useCallback((signal: AbortSignal) => id === null ? Promise.resolve(null) : fetchLinuxTrial(id, signal), [id]), id !== null);
}

export function useLinuxEvaluation(
  id: string | null,
): ReturnType<typeof useResource<LinuxEvaluation | null>> {
  return useResource(
    useCallback(
      (signal: AbortSignal) => id === null ? Promise.resolve(null) : fetchLinuxEvaluation(id, signal),
      [id],
    ),
    id !== null,
  );
}
