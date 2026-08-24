import { useCallback, useEffect, useState } from "react";

import {
  fetchTrialIntegrityVerification,
  fetchTrialArchive,
  type TrialArchiveKind,
  type TrialArchiveQuery,
  type TrialArchiveResponse,
  type TrialIntegrityVerification,
} from "./trialArchiveContracts";

export type TrialArchiveLoadState =
  | { readonly status: "loading"; readonly data: TrialArchiveResponse | null }
  | { readonly status: "success"; readonly data: TrialArchiveResponse }
  | {
      readonly status: "error";
      readonly error: Error;
      readonly isRetrying: boolean;
      readonly data: TrialArchiveResponse | null;
    };

function stateData(state: TrialArchiveLoadState): TrialArchiveResponse | null {
  return state.data;
}

function normalizeError(error: unknown): Error {
  return error instanceof Error
    ? error
    : new Error("读取试验档案失败：请求抛出了非标准错误。请检查后端日志。");
}

interface TrialArchiveSnapshot {
  readonly queryKey: string;
  readonly state: TrialArchiveLoadState;
}

export function useTrialArchive(query: TrialArchiveQuery): {
  readonly state: TrialArchiveLoadState;
  readonly reload: () => void;
} {
  const queryKey = `${query.page}:${query.pageSize}:${query.kind ?? "all"}:${query.status ?? "all"}`;
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [snapshot, setSnapshot] = useState<TrialArchiveSnapshot>({
    queryKey,
    state: { status: "loading", data: null },
  });
  const state: TrialArchiveLoadState = snapshot.queryKey === queryKey
    ? snapshot.state
    : { status: "loading", data: null };

  useEffect(() => {
    const controller = new AbortController();
    const request: TrialArchiveQuery = {
      page: query.page,
      pageSize: query.pageSize,
      kind: query.kind,
      status: query.status,
    };

    setSnapshot((current) => ({
      queryKey,
      state: {
        status: "loading",
        data: current.queryKey === queryKey ? stateData(current.state) : null,
      },
    }));

    void fetchTrialArchive(request, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        setSnapshot({ queryKey, state: { status: "success", data } });
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setSnapshot((current) => ({
          queryKey,
          state: {
            status: "error",
            error: normalizeError(error),
            isRetrying: false,
            data: current.queryKey === queryKey ? stateData(current.state) : null,
          },
        }));
      });

    return () => controller.abort();
  }, [query.kind, query.page, query.pageSize, query.status, queryKey, requestVersion]);

  return {
    state,
    reload: useCallback(() => setRequestVersion((current) => current + 1), []),
  };
}

export type TrialIntegrityLoadState =
  | { readonly status: "idle" }
  | { readonly status: "loading" }
  | { readonly status: "success"; readonly data: TrialIntegrityVerification }
  | { readonly status: "error"; readonly error: Error };

export function useTrialIntegrityVerification(
  kind: TrialArchiveKind | null,
  trialId: string | null,
): TrialIntegrityLoadState {
  const [state, setState] = useState<TrialIntegrityLoadState>({ status: "idle" });

  useEffect(() => {
    if (kind === null || trialId === null) {
      setState({ status: "idle" });
      return undefined;
    }
    const controller = new AbortController();
    setState({ status: "loading" });
    void fetchTrialIntegrityVerification(kind, trialId, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setState({ status: "success", data });
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        if (!controller.signal.aborted) setState({ status: "error", error: normalizeError(error) });
      });
    return () => controller.abort();
  }, [kind, trialId]);

  return state;
}
