import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchWorldModelDetail,
  fetchWorldModels,
  fetchWorldSnapshot,
  type SnapshotDetail,
  type WorldModelDetail,
  type WorldModelsResponse,
} from "./worldModelContracts";

export type WorldModelsLoadState =
  | { readonly status: "loading"; readonly data: WorldModelsResponse | null }
  | { readonly status: "success"; readonly data: WorldModelsResponse }
  | {
      readonly status: "error";
      readonly error: Error;
      readonly isRetrying: boolean;
      readonly data: WorldModelsResponse | null;
    };

export type WorldModelDetailLoadState =
  | { readonly status: "idle" }
  | { readonly status: "loading"; readonly data: WorldModelDetail | null }
  | { readonly status: "success"; readonly data: WorldModelDetail }
  | {
      readonly status: "error";
      readonly error: Error;
      readonly isRetrying: boolean;
      readonly data: WorldModelDetail | null;
    };

export type WorldSnapshotDetailLoadState =
  | { readonly status: "idle" }
  | { readonly status: "loading"; readonly data: SnapshotDetail | null }
  | { readonly status: "success"; readonly data: SnapshotDetail }
  | {
      readonly status: "error";
      readonly error: Error;
      readonly isRetrying: boolean;
      readonly data: SnapshotDetail | null;
    };

export interface UseWorldModelsResult {
  readonly state: WorldModelsLoadState;
  readonly reload: () => void;
}

export interface UseWorldModelDetailResult {
  readonly state: WorldModelDetailLoadState;
  readonly reload: () => void;
}

export interface UseWorldSnapshotDetailResult {
  readonly state: WorldSnapshotDetailLoadState;
  readonly reload: () => void;
}

function normalizeWorldModelsError(error: unknown): Error {
  return error instanceof Error
    ? error
    : new Error("读取世界模型失败：请求抛出了非标准错误。请检查浏览器控制台和后端日志。");
}

function normalizeWorldModelDetailError(error: unknown): Error {
  return error instanceof Error
    ? error
    : new Error("读取不可变快照失败：请求抛出了非标准错误。请检查浏览器控制台和后端日志。");
}

function normalizeWorldSnapshotDetailError(error: unknown): Error {
  return error instanceof Error
    ? error
    : new Error("读取历史快照失败：请求抛出了非标准错误。请检查浏览器控制台和后端日志。");
}

function worldModelsData(state: WorldModelsLoadState): WorldModelsResponse | null {
  return state.data;
}

function worldModelDetailData(
  state: WorldModelDetailLoadState,
  worldModelId: string,
): WorldModelDetail | null {
  if (state.status === "idle" || state.data === null) {
    return null;
  }

  return state.data.id === worldModelId ? state.data : null;
}

function worldSnapshotDetailData(
  state: WorldSnapshotDetailLoadState,
  worldModelId: string,
  snapshotId: string,
): SnapshotDetail | null {
  if (state.status === "idle" || state.data === null) {
    return null;
  }

  return state.data.world_model_id === worldModelId && state.data.id === snapshotId
    ? state.data
    : null;
}

export function useWorldModels(): UseWorldModelsResult {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<WorldModelsLoadState>({
    status: "loading",
    data: null,
  });
  const hasError = useRef<boolean>(false);

  useEffect(() => {
    const controller = new AbortController();

    setState((currentState) =>
      hasError.current && currentState.status === "error"
        ? { ...currentState, isRetrying: true }
        : { status: "loading", data: worldModelsData(currentState) },
    );

    void fetchWorldModels(controller.signal)
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
          error: normalizeWorldModelsError(error),
          isRetrying: false,
          data: worldModelsData(currentState),
        }));
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

export function useWorldModelDetail(
  worldModelId: string | null,
): UseWorldModelDetailResult {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<WorldModelDetailLoadState>({ status: "idle" });
  const hasError = useRef<boolean>(false);
  const previousWorldModelId = useRef<string | null>(null);

  useEffect(() => {
    if (worldModelId === null) {
      hasError.current = false;
      previousWorldModelId.current = null;
      setState({ status: "idle" });
      return;
    }

    if (previousWorldModelId.current !== worldModelId) {
      hasError.current = false;
      previousWorldModelId.current = worldModelId;
    }

    const controller = new AbortController();

    setState((currentState) =>
      hasError.current && currentState.status === "error"
        ? { ...currentState, isRetrying: true }
        : {
            status: "loading",
            data: worldModelDetailData(currentState, worldModelId),
          },
    );

    void fetchWorldModelDetail(worldModelId, controller.signal)
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
          error: normalizeWorldModelDetailError(error),
          isRetrying: false,
          data: worldModelDetailData(currentState, worldModelId),
        }));
      });

    return () => {
      controller.abort();
    };
  }, [requestVersion, worldModelId]);

  const reload = useCallback((): void => {
    setRequestVersion((currentVersion) => currentVersion + 1);
  }, []);

  return { state, reload };
}

export function useWorldSnapshotDetail(
  worldModelId: string | null,
  snapshotId: string | null,
): UseWorldSnapshotDetailResult {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<WorldSnapshotDetailLoadState>({ status: "idle" });
  const hasError = useRef<boolean>(false);
  const previousRequestKey = useRef<string | null>(null);

  useEffect(() => {
    if (worldModelId === null || snapshotId === null) {
      hasError.current = false;
      previousRequestKey.current = null;
      setState({ status: "idle" });
      return;
    }

    const requestKey = `${worldModelId}:${snapshotId}`;
    if (previousRequestKey.current !== requestKey) {
      hasError.current = false;
      previousRequestKey.current = requestKey;
    }

    const controller = new AbortController();

    setState((currentState) =>
      hasError.current && currentState.status === "error"
        ? { ...currentState, isRetrying: true }
        : {
            status: "loading",
            data: worldSnapshotDetailData(currentState, worldModelId, snapshotId),
          },
    );

    void fetchWorldSnapshot(worldModelId, snapshotId, controller.signal)
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
          error: normalizeWorldSnapshotDetailError(error),
          isRetrying: false,
          data: worldSnapshotDetailData(currentState, worldModelId, snapshotId),
        }));
      });

    return () => {
      controller.abort();
    };
  }, [requestVersion, snapshotId, worldModelId]);

  const reload = useCallback((): void => {
    setRequestVersion((currentVersion) => currentVersion + 1);
  }, []);

  return { state, reload };
}
