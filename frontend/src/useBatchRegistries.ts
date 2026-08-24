import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchBatchRegistries,
  fetchBatchRegistryCandidates,
  fetchBatchRegistry,
  type MatraixBatchRegistriesQuery,
  type MatraixBatchRegistriesResponse,
  type MatraixBatchRegistryCandidatesQuery,
  type MatraixBatchRegistryCandidatesResponse,
  type MatraixBatchRegistryDetail,
} from "./batchRegistryContracts";

export type BatchRegistryCandidatesLoadState =
  | { readonly status: "loading"; readonly data: MatraixBatchRegistryCandidatesResponse | null }
  | { readonly status: "success"; readonly data: MatraixBatchRegistryCandidatesResponse }
  | {
      readonly status: "error";
      readonly error: Error;
      readonly isRetrying: boolean;
      readonly data: MatraixBatchRegistryCandidatesResponse | null;
    };

export type BatchRegistriesLoadState =
  | { readonly status: "loading"; readonly data: MatraixBatchRegistriesResponse | null }
  | { readonly status: "success"; readonly data: MatraixBatchRegistriesResponse }
  | {
      readonly status: "error";
      readonly error: Error;
      readonly isRetrying: boolean;
      readonly data: MatraixBatchRegistriesResponse | null;
    };

export type BatchRegistryDetailLoadState =
  | { readonly status: "idle" }
  | { readonly status: "loading"; readonly data: MatraixBatchRegistryDetail | null }
  | { readonly status: "success"; readonly data: MatraixBatchRegistryDetail }
  | {
      readonly status: "error";
      readonly error: Error;
      readonly isRetrying: boolean;
      readonly data: MatraixBatchRegistryDetail | null;
    };

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function normalizeError(error: unknown, operation: string): Error {
  return error instanceof Error
    ? error
    : new Error(`${operation}失败：请求抛出了非标准错误。请检查后端日志。`);
}

function directoryData(
  state: BatchRegistriesLoadState,
): MatraixBatchRegistriesResponse | null {
  return state.data;
}

function candidatesData(
  state: BatchRegistryCandidatesLoadState,
): MatraixBatchRegistryCandidatesResponse | null {
  return state.data;
}

export function useBatchRegistryCandidates(query: MatraixBatchRegistryCandidatesQuery): {
  readonly state: BatchRegistryCandidatesLoadState;
  readonly reload: () => void;
} {
  const queryKey = `${query.page}:${query.pageSize}:${query.kind ?? "all"}`;
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [snapshot, setSnapshot] = useState<{
    readonly queryKey: string;
    readonly state: BatchRegistryCandidatesLoadState;
  }>({ queryKey, state: { status: "loading", data: null } });
  const state = snapshot.queryKey === queryKey
    ? snapshot.state
    : { status: "loading" as const, data: null };

  useEffect(() => {
    const controller = new AbortController();
    const request: MatraixBatchRegistryCandidatesQuery = {
      page: query.page,
      pageSize: query.pageSize,
      kind: query.kind,
    };
    setSnapshot((current) => ({
      queryKey,
      state: {
        status: "loading",
        data: current.queryKey === queryKey ? candidatesData(current.state) : null,
      },
    }));
    void fetchBatchRegistryCandidates(request, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setSnapshot({ queryKey, state: { status: "success", data } });
        }
      })
      .catch((error: unknown) => {
        if (isAbortError(error)) return;
        setSnapshot((current) => ({
          queryKey,
          state: {
            status: "error",
            error: normalizeError(error, "读取 Batch Registry 候选父运行"),
            isRetrying: false,
            data: current.queryKey === queryKey ? candidatesData(current.state) : null,
          },
        }));
      });
    return () => controller.abort();
  }, [query.kind, query.page, query.pageSize, queryKey, requestVersion]);

  return {
    state,
    reload: useCallback(() => setRequestVersion((current) => current + 1), []),
  };
}

export function useBatchRegistries(query: MatraixBatchRegistriesQuery): {
  readonly state: BatchRegistriesLoadState;
  readonly reload: () => void;
} {
  const queryKey = `${query.page}:${query.pageSize}`;
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [snapshot, setSnapshot] = useState<{
    readonly queryKey: string;
    readonly state: BatchRegistriesLoadState;
  }>({ queryKey, state: { status: "loading", data: null } });
  const state = snapshot.queryKey === queryKey
    ? snapshot.state
    : { status: "loading" as const, data: null };

  useEffect(() => {
    const controller = new AbortController();
    const request: MatraixBatchRegistriesQuery = {
      page: query.page,
      pageSize: query.pageSize,
    };
    setSnapshot((current) => ({
      queryKey,
      state: {
        status: "loading",
        data: current.queryKey === queryKey ? directoryData(current.state) : null,
      },
    }));
    void fetchBatchRegistries(request, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) {
          setSnapshot({ queryKey, state: { status: "success", data } });
        }
      })
      .catch((error: unknown) => {
        if (isAbortError(error)) return;
        setSnapshot((current) => ({
          queryKey,
          state: {
            status: "error",
            error: normalizeError(error, "读取批量试验目录"),
            isRetrying: false,
            data: current.queryKey === queryKey ? directoryData(current.state) : null,
          },
        }));
      });
    return () => controller.abort();
  }, [query.page, query.pageSize, queryKey, requestVersion]);

  return {
    state,
    reload: useCallback(() => setRequestVersion((current) => current + 1), []),
  };
}

export function useBatchRegistry(registryId: string | null): {
  readonly state: BatchRegistryDetailLoadState;
  readonly reload: () => void;
} {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<BatchRegistryDetailLoadState>({ status: "idle" });
  const previousId = useRef<string | null>(null);

  useEffect(() => {
    if (registryId === null) {
      previousId.current = null;
      setState({ status: "idle" });
      return;
    }
    const isNewRegistry = previousId.current !== registryId;
    previousId.current = registryId;
    const controller = new AbortController();
    setState((current) => ({
      status: "loading",
      data: isNewRegistry || current.status === "idle" ? null : current.data,
    }));
    void fetchBatchRegistry(registryId, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setState({ status: "success", data });
      })
      .catch((error: unknown) => {
        if (isAbortError(error)) return;
        setState((current) => ({
          status: "error",
          error: normalizeError(error, "读取批量试验详情"),
          isRetrying: false,
          data: current.status === "idle" ? null : current.data,
        }));
      });
    return () => controller.abort();
  }, [registryId, requestVersion]);

  return {
    state,
    reload: useCallback(() => setRequestVersion((current) => current + 1), []),
  };
}
