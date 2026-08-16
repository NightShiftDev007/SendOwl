import { useCallback, useEffect, useState } from "react";

import {
  fetchLinuxReadiness,
  fetchLinuxEvaluation,
  fetchLinuxEvaluationProgress,
  fetchLinuxEvaluations,
  fetchLinuxTasks,
  fetchLinuxTrial,
  fetchLinuxTrials,
  type LinuxReadiness,
  type LinuxEvaluation,
  type LinuxTask,
  type LinuxTrial,
} from "./linuxArtifactContracts";
import { useProgressDrivenResource } from "./parentProgress";

type LoadState<T> =
  | { readonly status: "loading"; readonly data: T | null }
  | { readonly status: "success"; readonly data: T }
  | { readonly status: "error"; readonly error: Error; readonly data: T | null };

function useResource<T>(
  loader: (signal: AbortSignal) => Promise<T>,
  poll: boolean,
  shouldPoll: ((data: T) => boolean) | null,
): { readonly state: LoadState<T>; readonly reload: () => void } {
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
    if (!poll || state.status !== "success" || (shouldPoll !== null && !shouldPoll(state.data))) {
      return undefined;
    }
    const timer = window.setInterval(() => setVersion((current) => current + 1), 5_000);
    return () => window.clearInterval(timer);
  }, [poll, shouldPoll, state]);
  return { state, reload: useCallback(() => setVersion((current) => current + 1), []) };
}

export function useLinuxReadiness(): ReturnType<typeof useResource<LinuxReadiness>> {
  return useResource(useCallback((signal: AbortSignal) => fetchLinuxReadiness(signal), []), true, null);
}

export function useLinuxTasks(): ReturnType<typeof useResource<readonly LinuxTask[]>> {
  return useResource(useCallback((signal: AbortSignal) => fetchLinuxTasks(signal), []), false, null);
}

export function useLinuxTrials(page: number): ReturnType<typeof useResource<Awaited<ReturnType<typeof fetchLinuxTrials>>>> {
  return useResource(useCallback((signal: AbortSignal) => fetchLinuxTrials(page, signal), [page]), false, null);
}

export function useLinuxEvaluations(
  page: number,
): ReturnType<typeof useResource<Awaited<ReturnType<typeof fetchLinuxEvaluations>>>> {
  return useResource(
    useCallback((signal: AbortSignal) => fetchLinuxEvaluations(page, signal), [page]),
    false,
    null,
  );
}

export function useLinuxTrial(id: string | null): ReturnType<typeof useResource<LinuxTrial | null>> {
  const loader = useCallback(
    (signal: AbortSignal) => id === null ? Promise.resolve(null) : fetchLinuxTrial(id, signal),
    [id],
  );
  const active = useCallback(
    (data: LinuxTrial | null) => data !== null && (data.status === "queued" || data.status === "running"),
    [],
  );
  return useResource(loader, id !== null, active);
}

export function useLinuxEvaluation(
  id: string | null,
): ReturnType<typeof useProgressDrivenResource<LinuxEvaluation>> {
  return useProgressDrivenResource(
    id,
    fetchLinuxEvaluation,
    fetchLinuxEvaluationProgress,
    5_000,
    "读取 Linux Evaluation",
  );
}
