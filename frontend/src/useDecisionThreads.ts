import { useCallback, useEffect, useRef, useState } from "react";

import {
  appendDecisionThreadRevision,
  createDecisionThread,
  createDecisionThreadDraft,
  fetchDecisionThread,
  fetchDecisionThreads,
  type DecisionThreadContextRequest,
  type DecisionThreadCreateRequest,
  type DecisionThreadDetail,
  type DecisionThreadDraftCreateRequest,
  type DecisionThreadsResponse,
} from "./decisionThreadContracts";

type DirectoryState = { readonly status: "loading"; readonly data: DecisionThreadsResponse | null }
  | { readonly status: "success"; readonly data: DecisionThreadsResponse }
  | { readonly status: "error"; readonly data: DecisionThreadsResponse | null; readonly error: Error };
type DetailState = { readonly status: "idle"; readonly data: null }
  | { readonly status: "loading"; readonly data: DecisionThreadDetail | null }
  | { readonly status: "success"; readonly data: DecisionThreadDetail }
  | { readonly status: "error"; readonly data: DecisionThreadDetail | null; readonly error: Error };

function errorValue(value: unknown): Error {
  return value instanceof Error ? value : new Error("Decision thread request failed with a non-standard error.");
}

export function useDecisionThreads(selectedId: string | null): {
  readonly directory: DirectoryState;
  readonly detail: DetailState;
  readonly submitting: boolean;
  readonly reload: () => void;
  readonly create: (request: DecisionThreadCreateRequest) => Promise<DecisionThreadDetail | null>;
  readonly createDraft: (request: DecisionThreadDraftCreateRequest) => Promise<DecisionThreadDetail | null>;
  readonly append: (request: DecisionThreadContextRequest) => Promise<DecisionThreadDetail | null>;
} {
  const [version, setVersion] = useState(0);
  const [directory, setDirectory] = useState<DirectoryState>({ status: "loading", data: null });
  const [detail, setDetail] = useState<DetailState>({ status: "idle", data: null });
  const [submitting, setSubmitting] = useState(false);
  const submitController = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setDirectory((current) => ({ status: "loading", data: current.data }));
    void fetchDecisionThreads(controller.signal)
      .then((data) => setDirectory({ status: "success", data }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setDirectory((current) => ({ status: "error", data: current.data, error: errorValue(error) }));
      });
    return () => controller.abort();
  }, [version]);

  useEffect(() => {
    if (selectedId === null) {
      setDetail({ status: "idle", data: null });
      return undefined;
    }
    const controller = new AbortController();
    setDetail((current) => ({ status: "loading", data: current.data?.id === selectedId ? current.data : null }));
    void fetchDecisionThread(selectedId, controller.signal)
      .then((data) => setDetail({ status: "success", data }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setDetail((current) => ({ status: "error", data: current.data, error: errorValue(error) }));
      });
    return () => controller.abort();
  }, [selectedId, version]);

  useEffect(() => () => submitController.current?.abort(), []);

  const submit = useCallback(async (
    action: (signal: AbortSignal) => Promise<DecisionThreadDetail>,
  ): Promise<DecisionThreadDetail | null> => {
    if (submitController.current !== null) return null;
    const controller = new AbortController();
    submitController.current = controller;
    setSubmitting(true);
    try {
      const result = await action(controller.signal);
      setVersion((current) => current + 1);
      return result;
    } finally {
      if (submitController.current === controller) {
        submitController.current = null;
        setSubmitting(false);
      }
    }
  }, []);

  return {
    directory,
    detail,
    submitting,
    reload: () => setVersion((current) => current + 1),
    create: (request) => submit((signal) => createDecisionThread(request, signal)),
    createDraft: (request) => submit((signal) => createDecisionThreadDraft(request, signal)),
    append: (request) => selectedId === null ? Promise.resolve(null) : submit((signal) => appendDecisionThreadRevision(selectedId, request, signal)),
  };
}
