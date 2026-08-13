import { useCallback, useEffect, useState } from "react";

import {
  fetchEvidenceBundle,
  fetchEvidenceBundles,
  type EvidenceBundleDetail,
  type EvidenceBundlesResponse,
} from "./evidenceBundleContracts";

type DirectoryState =
  | { readonly status: "loading" }
  | { readonly status: "success"; readonly data: EvidenceBundlesResponse }
  | { readonly status: "error"; readonly error: Error; readonly isRetrying: boolean };

type DetailState =
  | { readonly status: "idle" }
  | { readonly status: "loading" }
  | { readonly status: "success"; readonly data: EvidenceBundleDetail }
  | { readonly status: "error"; readonly error: Error; readonly isRetrying: boolean };

function normalizeError(error: unknown, operation: string): Error {
  return error instanceof Error
    ? error
    : new Error(`${operation}失败：请求抛出了非标准错误。`);
}

export function useEvidenceBundles(): {
  readonly state: DirectoryState;
  readonly reload: () => void;
} {
  const [version, setVersion] = useState<number>(0);
  const [state, setState] = useState<DirectoryState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    setState((current) => current.status === "error"
      ? { ...current, isRetrying: true }
      : { status: "loading" });
    void fetchEvidenceBundles(controller.signal)
      .then((data) => setState({ status: "success", data }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState({
          status: "error",
          error: normalizeError(error, "读取 Evidence Bundle 目录"),
          isRetrying: false,
        });
      });
    return () => controller.abort();
  }, [version]);

  return {
    state,
    reload: useCallback(() => setVersion((current) => current + 1), []),
  };
}

export function useEvidenceBundle(bundleId: string | null): {
  readonly state: DetailState;
  readonly reload: () => void;
} {
  const [version, setVersion] = useState<number>(0);
  const [state, setState] = useState<DetailState>({ status: "idle" });

  useEffect(() => {
    if (bundleId === null) {
      setState({ status: "idle" });
      return;
    }
    const controller = new AbortController();
    setState((current) => current.status === "error"
      ? { ...current, isRetrying: true }
      : { status: "loading" });
    void fetchEvidenceBundle(bundleId, controller.signal)
      .then((data) => setState({ status: "success", data }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState({
          status: "error",
          error: normalizeError(error, "读取 Evidence Bundle"),
          isRetrying: false,
        });
      });
    return () => controller.abort();
  }, [bundleId, version]);

  return {
    state,
    reload: useCallback(() => setVersion((current) => current + 1), []),
  };
}
