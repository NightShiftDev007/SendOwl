import { useCallback, useEffect, useState } from "react";

import {
  fetchPolicyDocument,
  fetchPolicyDocuments,
  fetchPolicyVersionContent,
  type PolicyDocumentDetail,
  type PolicyDocumentSummary,
  type PolicyVersionContent,
} from "./policyEvidenceContracts";

type LoadState<T> =
  | { readonly status: "loading"; readonly data: T | null }
  | { readonly status: "success"; readonly data: T }
  | { readonly status: "error"; readonly error: Error; readonly data: T | null };

function normalizedError(error: unknown, operation: string): Error {
  return error instanceof Error ? error : new Error(`${operation}失败：请求抛出了非标准错误。`);
}

export function usePolicyDocuments(page: number): {
  readonly state: LoadState<{
    readonly items: readonly PolicyDocumentSummary[];
    readonly total: number;
  }>;
  readonly reload: () => void;
} {
  const [version, setVersion] = useState<number>(0);
  const [state, setState] = useState<LoadState<{
    readonly items: readonly PolicyDocumentSummary[];
    readonly total: number;
  }>>({ status: "loading", data: null });
  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading", data: null });
    void fetchPolicyDocuments(page, controller.signal)
      .then((response) => setState({
        status: "success",
        data: { items: response.items, total: response.total },
      }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState((current) => ({
          status: "error",
          error: normalizedError(error, "读取政策目录"),
          data: current.data,
        }));
      });
    return () => controller.abort();
  }, [page, version]);
  return {
    state,
    reload: useCallback(() => setVersion((current) => current + 1), []),
  };
}

export function usePolicyDocument(documentId: string | null): {
  readonly state: LoadState<PolicyDocumentDetail | null>;
  readonly reload: () => void;
} {
  const [version, setVersion] = useState<number>(0);
  const [state, setState] = useState<LoadState<PolicyDocumentDetail | null>>({
    status: "success",
    data: null,
  });
  useEffect(() => {
    if (documentId === null) {
      setState({ status: "success", data: null });
      return undefined;
    }
    const controller = new AbortController();
    setState({ status: "loading", data: null });
    void fetchPolicyDocument(documentId, controller.signal)
      .then((data) => setState({ status: "success", data }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState((current) => ({
          status: "error",
          error: normalizedError(error, "读取政策详情"),
          data: current.data,
        }));
      });
    return () => controller.abort();
  }, [documentId, version]);
  return {
    state,
    reload: useCallback(() => setVersion((current) => current + 1), []),
  };
}

export function usePolicyVersionContent(
  documentId: string | null,
  versionId: string | null,
): LoadState<PolicyVersionContent | null> {
  const [state, setState] = useState<LoadState<PolicyVersionContent | null>>({
    status: "success",
    data: null,
  });
  useEffect(() => {
    if (documentId === null || versionId === null) {
      setState({ status: "success", data: null });
      return undefined;
    }
    const controller = new AbortController();
    setState({ status: "loading", data: null });
    void fetchPolicyVersionContent(documentId, versionId, controller.signal)
      .then((data) => setState({ status: "success", data }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState({
          status: "error",
          error: normalizedError(error, "读取政策正文"),
          data: null,
        });
      });
    return () => controller.abort();
  }, [documentId, versionId]);
  return state;
}
