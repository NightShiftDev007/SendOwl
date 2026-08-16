import { useCallback, useEffect, useState } from "react";

import {
  fetchSurveyExperiment,
  fetchSurveyExperimentProgress,
  fetchSurveyExperiments,
  fetchSurveyReadiness,
  type SurveyExperimentDetail,
  type SurveyExperimentSummary,
  type SurveyReadiness,
} from "./surveyContracts";
import { useProgressDrivenResource } from "./parentProgress";

type ReadinessState =
  | { readonly status: "loading" }
  | { readonly status: "success"; readonly data: SurveyReadiness }
  | { readonly status: "error"; readonly error: Error; readonly isRetrying: boolean };
type DirectoryState =
  | { readonly status: "loading" }
  | { readonly status: "success"; readonly items: readonly SurveyExperimentSummary[] }
  | { readonly status: "error"; readonly error: Error; readonly isRetrying: boolean };
type DetailState =
  | { readonly status: "idle" }
  | { readonly status: "loading" }
  | { readonly status: "success"; readonly data: SurveyExperimentDetail }
  | { readonly status: "error"; readonly error: Error; readonly isRetrying: boolean };

function errorValue(error: unknown, operation: string): Error {
  return error instanceof Error ? error : new Error(`${operation}失败：请求抛出了非标准错误。`);
}

export function useSurveyReadiness(): { readonly state: ReadinessState; readonly reload: () => void } {
  const [version, setVersion] = useState(0);
  const [state, setState] = useState<ReadinessState>({ status: "loading" });
  useEffect(() => {
    const controller = new AbortController();
    setState((current) => current.status === "error" ? { ...current, isRetrying: true } : { status: "loading" });
    void fetchSurveyReadiness(controller.signal).then((data) => setState({ status: "success", data })).catch((error: unknown) => {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setState({ status: "error", error: errorValue(error, "核验 Survey runtime"), isRetrying: false });
    });
    const interval = window.setInterval(() => setVersion((current) => current + 1), 10_000);
    return () => { controller.abort(); window.clearInterval(interval); };
  }, [version]);
  return { state, reload: useCallback(() => setVersion((current) => current + 1), []) };
}

export function useSurveyExperiments(): { readonly state: DirectoryState; readonly reload: () => void } {
  const [version, setVersion] = useState(0);
  const [state, setState] = useState<DirectoryState>({ status: "loading" });
  useEffect(() => {
    const controller = new AbortController();
    setState((current) => current.status === "error" ? { ...current, isRetrying: true } : { status: "loading" });
    void fetchSurveyExperiments(controller.signal).then((data) => setState({ status: "success", items: data.items })).catch((error: unknown) => {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setState({ status: "error", error: errorValue(error, "读取 Survey 实验目录"), isRetrying: false });
    });
    return () => controller.abort();
  }, [version]);
  return { state, reload: useCallback(() => setVersion((current) => current + 1), []) };
}

export function useSurveyExperiment(experimentId: string | null): { readonly state: DetailState; readonly reload: () => void } {
  const resource = useProgressDrivenResource(
    experimentId,
    fetchSurveyExperiment,
    fetchSurveyExperimentProgress,
    2_000,
    "读取 Survey 实验",
  );
  if (resource.state.status === "idle") return { state: { status: "idle" }, reload: resource.reload };
  if (resource.state.status === "loading") return { state: { status: "loading" }, reload: resource.reload };
  if (resource.state.status === "error") {
    return {
      state: {
        status: "error",
        error: resource.state.error,
        isRetrying: resource.state.isRetrying,
      },
      reload: resource.reload,
    };
  }
  return { state: resource.state, reload: resource.reload };
}
