import { useCallback, useEffect, useRef, useState } from "react";

import {
  enqueueSemanticWorldGraph,
  fetchSemanticWorldGraphEdgeHistory,
  fetchSemanticWorldGraphEvidenceTimeline,
  fetchSemanticWorldGraphPersonaMatches,
  fetchSemanticWorldGraphSearch,
  fetchSemanticWorldGraphSlice,
  fetchSemanticWorldGraphs,
  type SemanticWorldGraph,
  type SemanticWorldGraphEvidenceTimeline,
  type SemanticWorldGraphEdgeHistory,
  type SemanticWorldGraphPersonaMatches,
  type SemanticWorldGraphSearchResponse,
  type SemanticWorldGraphSlice,
  type SemanticWorldGraphSliceDirection,
  type SemanticWorldGraphsResponse,
} from "./worldModelContracts";
import { fetchSemanticReadiness } from "./semanticExperimentContracts";

export type SemanticWorldGraphsState =
  | { readonly status: "loading"; readonly data: SemanticWorldGraphsResponse | null }
  | { readonly status: "success"; readonly data: SemanticWorldGraphsResponse }
  | {
    readonly status: "error";
    readonly data: SemanticWorldGraphsResponse | null;
    readonly error: Error;
    readonly isRetrying: boolean;
  };

function normalizedError(error: unknown): Error {
  return error instanceof Error
    ? error
    : new Error("语义世界图请求抛出了非标准错误。");
}

export function useSemanticWorldGraphs(
  worldModelId: string | null,
  snapshotId: string | null,
): {
  readonly state: SemanticWorldGraphsState;
  readonly enqueueState: "idle" | "submitting";
  readonly selectedGraphId: string | null;
  readonly selectGraph: (graphId: string) => void;
  readonly enqueue: () => Promise<void>;
  readonly reload: () => void;
} {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<SemanticWorldGraphsState>({
    status: "loading",
    data: null,
  });
  const [enqueueState, setEnqueueState] = useState<"idle" | "submitting">("idle");
  const [selectedGraphId, setSelectedGraphId] = useState<string | null>(null);
  const enqueueController = useRef<AbortController | null>(null);

  useEffect(() => {
    if (worldModelId === null || snapshotId === null) {
      setState({ status: "success", data: { items: [], total: 0 } });
      return undefined;
    }
    const controller = new AbortController();
    setState((current) => ({ status: "loading", data: current.data }));
    void fetchSemanticWorldGraphs(worldModelId, snapshotId, controller.signal)
      .then((data) => setState({ status: "success", data }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState((current) => ({
          status: "error",
          data: current.data,
          error: normalizedError(error),
          isRetrying: false,
        }));
      });
    return () => controller.abort();
  }, [requestVersion, snapshotId, worldModelId]);

  useEffect(() => {
    const data = state.data;
    if (data === null || !data.items.some((item) => ["queued", "running"].includes(item.status))) {
      return undefined;
    }
    const timeout = window.setTimeout(() => setRequestVersion((current) => current + 1), 2_000);
    return () => window.clearTimeout(timeout);
  }, [state.data]);

  useEffect(() => () => enqueueController.current?.abort(), []);

  const reload = useCallback((): void => {
    setState((current) => current.status === "error"
      ? { ...current, isRetrying: true }
      : current);
    setRequestVersion((current) => current + 1);
  }, []);

  const enqueue = useCallback(async (): Promise<void> => {
    if (enqueueController.current !== null || worldModelId === null || snapshotId === null) return;
    const controller = new AbortController();
    enqueueController.current = controller;
    setEnqueueState("submitting");
    try {
      const readiness = await fetchSemanticReadiness(controller.signal);
      if (!readiness.semantic_runtime_ready) {
        throw new Error(
          "语义 Worker 尚未通过模型启动探测；图谱 POST 尚未发送。请配置 LLM_API_KEY、LLM_BASE_URL 和 LLM_MODEL_NAME。",
        );
      }
      const graph = await enqueueSemanticWorldGraph(worldModelId, snapshotId, controller.signal);
      setSelectedGraphId(graph.id);
      setRequestVersion((current) => current + 1);
    } catch (error: unknown) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setState((current) => ({
        status: "error",
        data: current.data,
        error: normalizedError(error),
        isRetrying: false,
      }));
    } finally {
      if (enqueueController.current === controller) {
        enqueueController.current = null;
        setEnqueueState("idle");
      }
    }
  }, [snapshotId, worldModelId]);

  return {
    state,
    enqueueState,
    selectedGraphId,
    selectGraph: setSelectedGraphId,
    enqueue,
    reload,
  };
}

export function selectedSemanticWorldGraph(
  response: SemanticWorldGraphsResponse | null,
  graphId: string | null,
): SemanticWorldGraph | null {
  if (response === null || graphId === null) return null;
  return response.items.find((graph) => graph.id === graphId) ?? null;
}

export type SemanticWorldGraphSliceState =
  | { readonly status: "idle"; readonly data: null }
  | { readonly status: "loading"; readonly data: null }
  | { readonly status: "success"; readonly data: SemanticWorldGraphSlice }
  | { readonly status: "error"; readonly data: null; readonly error: Error };

export function useSemanticWorldGraphSlice(
  graphId: string | null,
  rootNodeId: string | null,
  direction: SemanticWorldGraphSliceDirection,
  hops: number,
  maxNodes: number,
): {
  readonly state: SemanticWorldGraphSliceState;
  readonly reload: () => void;
} {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<SemanticWorldGraphSliceState>({
    status: "idle",
    data: null,
  });

  useEffect(() => {
    if (graphId === null || rootNodeId === null) {
      setState({ status: "idle", data: null });
      return undefined;
    }
    const controller = new AbortController();
    setState({ status: "loading", data: null });
    void fetchSemanticWorldGraphSlice(
      graphId,
      rootNodeId,
      direction,
      hops,
      maxNodes,
      controller.signal,
    )
      .then((data) => setState({ status: "success", data }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState({ status: "error", data: null, error: normalizedError(error) });
      });
    return () => controller.abort();
  }, [direction, graphId, hops, maxNodes, requestVersion, rootNodeId]);

  return {
    state,
    reload: () => setRequestVersion((current) => current + 1),
  };
}

export type SemanticWorldGraphTimelineState =
  | { readonly status: "idle"; readonly data: null }
  | { readonly status: "loading"; readonly data: null }
  | { readonly status: "success"; readonly data: SemanticWorldGraphEvidenceTimeline }
  | { readonly status: "error"; readonly data: null; readonly error: Error };

export function useSemanticWorldGraphTimeline(
  graphId: string | null,
): {
  readonly state: SemanticWorldGraphTimelineState;
  readonly reload: () => void;
} {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<SemanticWorldGraphTimelineState>({
    status: "idle",
    data: null,
  });

  useEffect(() => {
    if (graphId === null) {
      setState({ status: "idle", data: null });
      return undefined;
    }
    const controller = new AbortController();
    setState({ status: "loading", data: null });
    void fetchSemanticWorldGraphEvidenceTimeline(graphId, controller.signal)
      .then((data) => setState({ status: "success", data }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState({ status: "error", data: null, error: normalizedError(error) });
      });
    return () => controller.abort();
  }, [graphId, requestVersion]);

  return {
    state,
    reload: () => setRequestVersion((current) => current + 1),
  };
}

export type SemanticWorldGraphSearchState =
  | { readonly status: "idle"; readonly data: null }
  | { readonly status: "loading"; readonly data: null }
  | { readonly status: "success"; readonly data: SemanticWorldGraphSearchResponse }
  | { readonly status: "error"; readonly data: null; readonly error: Error };

export function useSemanticWorldGraphSearch(
  graphId: string | null,
  query: string | null,
): {
  readonly state: SemanticWorldGraphSearchState;
  readonly reload: () => void;
} {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<SemanticWorldGraphSearchState>({
    status: "idle",
    data: null,
  });

  useEffect(() => {
    if (graphId === null || query === null) {
      setState({ status: "idle", data: null });
      return undefined;
    }
    const controller = new AbortController();
    setState({ status: "loading", data: null });
    void fetchSemanticWorldGraphSearch(graphId, query, 20, controller.signal)
      .then((data) => setState({ status: "success", data }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState({ status: "error", data: null, error: normalizedError(error) });
      });
    return () => controller.abort();
  }, [graphId, query, requestVersion]);

  return {
    state,
    reload: () => setRequestVersion((current) => current + 1),
  };
}

export type SemanticWorldGraphEdgeHistoryState =
  | { readonly status: "idle"; readonly data: null }
  | { readonly status: "loading"; readonly data: null }
  | { readonly status: "success"; readonly data: SemanticWorldGraphEdgeHistory }
  | { readonly status: "error"; readonly data: null; readonly error: Error };

export function useSemanticWorldGraphEdgeHistory(
  graphId: string | null,
  edgeId: string | null,
): {
  readonly state: SemanticWorldGraphEdgeHistoryState;
  readonly reload: () => void;
} {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<SemanticWorldGraphEdgeHistoryState>({
    status: "idle",
    data: null,
  });

  useEffect(() => {
    if (graphId === null || edgeId === null) {
      setState({ status: "idle", data: null });
      return undefined;
    }
    const controller = new AbortController();
    setState({ status: "loading", data: null });
    void fetchSemanticWorldGraphEdgeHistory(graphId, edgeId, controller.signal)
      .then((data) => setState({ status: "success", data }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState({ status: "error", data: null, error: normalizedError(error) });
      });
    return () => controller.abort();
  }, [edgeId, graphId, requestVersion]);

  return {
    state,
    reload: () => setRequestVersion((current) => current + 1),
  };
}

export type SemanticWorldGraphPersonaMatchesState =
  | { readonly status: "idle"; readonly data: null }
  | { readonly status: "loading"; readonly data: null }
  | { readonly status: "success"; readonly data: SemanticWorldGraphPersonaMatches }
  | { readonly status: "error"; readonly data: null; readonly error: Error };

export function useSemanticWorldGraphPersonaMatches(
  graphId: string | null,
  nodeId: string | null,
  datasetId: string | null,
): {
  readonly state: SemanticWorldGraphPersonaMatchesState;
  readonly reload: () => void;
} {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<SemanticWorldGraphPersonaMatchesState>({
    status: "idle",
    data: null,
  });

  useEffect(() => {
    if (graphId === null || nodeId === null || datasetId === null) {
      setState({ status: "idle", data: null });
      return undefined;
    }
    const controller = new AbortController();
    setState({ status: "loading", data: null });
    void fetchSemanticWorldGraphPersonaMatches(
      graphId,
      nodeId,
      datasetId,
      20,
      controller.signal,
    )
      .then((data) => setState({ status: "success", data }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState({ status: "error", data: null, error: normalizedError(error) });
      });
    return () => controller.abort();
  }, [datasetId, graphId, nodeId, requestVersion]);

  return {
    state,
    reload: () => setRequestVersion((current) => current + 1),
  };
}
