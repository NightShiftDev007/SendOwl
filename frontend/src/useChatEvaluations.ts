import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchChatEvaluation,
  fetchChatEvaluationProgress,
  fetchChatEvaluations,
  fetchChatReadiness,
  fetchChatTasks,
  fetchChatTranscriptDelta,
  fetchChatTrialTrajectory,
  type ChatEvaluationDetail,
  type ChatEvaluationSummary,
  type ChatReadiness,
  type ChatTrial,
  type ChatTrialAtifProjection,
  type MatraixChatTask,
  mergeChatTranscriptDelta,
} from "./chatEvaluationContracts";
import type { ParentProgress } from "./parentProgress";

export type ChatReadinessLoadState =
  | { readonly status: "loading"; readonly data: ChatReadiness | null }
  | { readonly status: "success"; readonly data: ChatReadiness }
  | {
      readonly status: "error";
      readonly error: Error;
      readonly isRetrying: boolean;
      readonly data: ChatReadiness | null;
    };

export type ChatTasksLoadState =
  | { readonly status: "loading"; readonly items: readonly MatraixChatTask[] }
  | { readonly status: "success"; readonly items: readonly MatraixChatTask[] }
  | {
      readonly status: "error";
      readonly error: Error;
      readonly isRetrying: boolean;
      readonly items: readonly MatraixChatTask[];
    };

export type ChatEvaluationsLoadState =
  | {
      readonly status: "loading";
      readonly items: readonly ChatEvaluationSummary[];
      readonly total: number;
      readonly pageSize: number;
    }
  | {
      readonly status: "success";
      readonly items: readonly ChatEvaluationSummary[];
      readonly total: number;
      readonly pageSize: number;
    }
  | {
      readonly status: "error";
      readonly error: Error;
      readonly isRetrying: boolean;
      readonly items: readonly ChatEvaluationSummary[];
      readonly total: number;
      readonly pageSize: number;
    };

export type ChatEvaluationDetailLoadState =
  | { readonly status: "idle" }
  | { readonly status: "loading"; readonly data: ChatEvaluationDetail | null }
  | { readonly status: "success"; readonly data: ChatEvaluationDetail }
  | {
      readonly status: "error";
      readonly error: Error;
      readonly isRetrying: boolean;
      readonly data: ChatEvaluationDetail | null;
    };

export type ChatTrialTrajectoryLoadState =
  | { readonly status: "idle" }
  | { readonly status: "loading" }
  | { readonly status: "success"; readonly data: ChatTrialAtifProjection }
  | { readonly status: "error"; readonly error: Error; readonly isRetrying: boolean };

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function normalizeError(error: unknown, operation: string): Error {
  return error instanceof Error
    ? error
    : new Error(`${operation}失败：请求抛出了非标准错误。请检查后端日志。`);
}

export function useChatReadiness(): {
  readonly state: ChatReadinessLoadState;
  readonly reload: () => void;
} {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<ChatReadinessLoadState>({
    status: "loading",
    data: null,
  });

  useEffect(() => {
    const controller = new AbortController();

    setState((current) => ({
      status: "loading",
      data: current.data,
    }));

    void fetchChatReadiness(controller.signal)
      .then((data) => {
        setState({ status: "success", data });
      })
      .catch((error: unknown) => {
        if (isAbortError(error)) return;
        setState((current) => ({
          status: "error",
          error: normalizeError(error, "核验 Chat runtime"),
          isRetrying: false,
          data: current.data,
        }));
      });

    const intervalId = window.setInterval(() => {
      setRequestVersion((current) => current + 1);
    }, 10_000);

    return () => {
      controller.abort();
      window.clearInterval(intervalId);
    };
  }, [requestVersion]);

  return {
    state,
    reload: useCallback(() => setRequestVersion((current) => current + 1), []),
  };
}

export function useChatTasks(): {
  readonly state: ChatTasksLoadState;
  readonly reload: () => void;
} {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<ChatTasksLoadState>({
    status: "loading",
    items: [],
  });

  useEffect(() => {
    const controller = new AbortController();
    setState((current) => ({ status: "loading", items: current.items }));
    void fetchChatTasks(controller.signal)
      .then((response) => setState({ status: "success", items: response.items }))
      .catch((error: unknown) => {
        if (isAbortError(error)) return;
        setState((current) => ({
          status: "error",
          error: normalizeError(error, "读取 Chat 任务目录"),
          isRetrying: false,
          items: current.items,
        }));
      });
    return () => controller.abort();
  }, [requestVersion]);

  return {
    state,
    reload: useCallback(() => setRequestVersion((current) => current + 1), []),
  };
}

export function useChatEvaluations(page: number): {
  readonly state: ChatEvaluationsLoadState;
  readonly reload: () => void;
} {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<ChatEvaluationsLoadState>({
    status: "loading",
    items: [],
    total: 0,
    pageSize: 20,
  });

  useEffect(() => {
    const controller = new AbortController();
    setState((current) => ({
      status: "loading",
      items: current.items,
      total: current.total,
      pageSize: current.pageSize,
    }));
    void fetchChatEvaluations(page, controller.signal)
      .then((response) => setState({
        status: "success",
        items: response.items,
        total: response.total,
        pageSize: response.page_size,
      }))
      .catch((error: unknown) => {
        if (isAbortError(error)) return;
        setState((current) => ({
          status: "error",
          error: normalizeError(error, "读取 Chat Evaluation 目录"),
          isRetrying: false,
          items: current.items,
          total: current.total,
          pageSize: current.pageSize,
        }));
      });
    return () => controller.abort();
  }, [page, requestVersion]);

  return {
    state,
    reload: useCallback(() => setRequestVersion((current) => current + 1), []),
  };
}

export function useChatEvaluation(
  evaluationId: string | null,
): {
  readonly state: ChatEvaluationDetailLoadState;
  readonly reload: () => void;
} {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<ChatEvaluationDetailLoadState>(
    evaluationId === null ? { status: "idle" } : { status: "loading", data: null },
  );
  const cursor = useRef<string>("0");
  const cursorInitialized = useRef<boolean>(false);
  const progress = useRef<ParentProgress | null>(null);
  const previousId = useRef<string | null>(null);

  useEffect(() => {
    const changedEvaluation = previousId.current !== evaluationId;
    if (changedEvaluation) {
      previousId.current = evaluationId;
      cursor.current = "0";
      cursorInitialized.current = false;
      progress.current = null;
    }
    if (evaluationId === null) {
      setState({ status: "idle" });
      return undefined;
    }
    const controller = new AbortController();
    setState((current) => ({
      status: "loading",
      data: changedEvaluation || current.status === "idle" ? null : current.data,
    }));
    void fetchChatEvaluation(evaluationId, controller.signal)
      .then((data) => setState({ status: "success", data }))
      .catch((error: unknown) => {
        if (isAbortError(error)) return;
        setState((current) => ({
          status: "error",
          error: normalizeError(error, "读取 Chat Evaluation"),
          isRetrying: false,
          data: current.status === "idle" ? null : current.data,
        }));
      });
    return () => controller.abort();
  }, [evaluationId, requestVersion]);

  useEffect(() => {
    if (evaluationId === null || state.status !== "success") return undefined;
    if (state.data.status === "succeeded" || state.data.status === "failed") return undefined;
    const controller = new AbortController();
    let timer: number | null = null;
    const poll = (): void => {
      void fetchChatEvaluationProgress(evaluationId, controller.signal)
        .then(async (nextProgress) => {
          if (nextProgress.id !== evaluationId) {
            throw new Error("轻量进度不属于当前 Chat Evaluation。");
          }
          const currentData = state.data;
          const runningCount = currentData.trials.filter(
            (trial) => trial.status === "running",
          ).length;
          const queuedCount = currentData.trials.filter(
            (trial) => trial.status === "queued",
          ).length;
          const statusChanged = nextProgress.status !== currentData.status
            || nextProgress.queued_trial_count !== queuedCount
            || nextProgress.running_trial_count !== runningCount
            || nextProgress.succeeded_trial_count !== currentData.succeeded_trial_count
            || nextProgress.failed_trial_count !== currentData.failed_trial_count;
          let nextData = statusChanged
            ? await fetchChatEvaluation(evaluationId, controller.signal)
            : currentData;
          const previousEventCount = progress.current?.event_count
            ?? currentData.trials.reduce(
              (total, trial) => total + trial.transcript.length,
              0,
            );
          if (nextProgress.event_count !== previousEventCount || !cursorInitialized.current) {
            const delta = await fetchChatTranscriptDelta(
              evaluationId,
              cursor.current,
              controller.signal,
            );
            nextData = mergeChatTranscriptDelta(nextData, delta);
            cursor.current = delta.next_event_sequence;
            cursorInitialized.current = true;
          }
          progress.current = nextProgress;
          setState({ status: "success", data: nextData });
          if (nextProgress.status === "queued" || nextProgress.status === "running") {
            timer = window.setTimeout(poll, 2_000);
          }
        })
        .catch((error: unknown) => {
          if (isAbortError(error)) return;
          setState((current) => ({
            status: "error",
            error: normalizeError(error, "读取 Chat Evaluation 进度"),
            isRetrying: false,
            data: current.status === "idle" ? null : current.data,
          }));
        });
    };
    timer = window.setTimeout(poll, 2_000);
    return () => {
      controller.abort();
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [evaluationId, state]);

  return {
    state,
    reload: useCallback(() => {
      cursor.current = "0";
      cursorInitialized.current = false;
      progress.current = null;
      setRequestVersion((current) => current + 1);
    }, []),
  };
}

export function useChatTrialTrajectory(
  trial: ChatTrial | null,
): {
  readonly state: ChatTrialTrajectoryLoadState;
  readonly reload: () => void;
} {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<ChatTrialTrajectoryLoadState>({ status: "idle" });
  const lastMessage = trial?.transcript.at(-1) ?? null;
  const revision = trial === null || lastMessage === null
    ? null
    : `${trial.id}:${trial.transcript.length}:${lastMessage.recorded_at}:${trial.result?.transcript_sha256 ?? "partial"}`;

  useEffect(() => {
    if (trial === null || revision === null) {
      setState({ status: "idle" });
      return;
    }
    const selectedTrial = trial;
    const controller = new AbortController();
    setState({ status: "loading" });
    void fetchChatTrialTrajectory(
      selectedTrial.id,
      selectedTrial.trial_sha256,
      controller.signal,
    )
      .then((data) => setState({ status: "success", data }))
      .catch((error: unknown) => {
        if (isAbortError(error)) return;
        setState({
          status: "error",
          error: normalizeError(error, "读取 ATIF trajectory"),
          isRetrying: false,
        });
      });
    return () => controller.abort();
  }, [revision, requestVersion]);

  return {
    state,
    reload: useCallback(() => setRequestVersion((current) => current + 1), []),
  };
}
