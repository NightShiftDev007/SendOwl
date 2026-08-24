import { useCallback, useEffect, useState } from "react";

import { fetchResearchSurveyReadiness, type ResearchSurveyReadiness } from "./researchSurveyContracts";

export type ResearchSurveyReadinessLoadState =
  | { readonly status: "loading" }
  | { readonly status: "success"; readonly data: ResearchSurveyReadiness }
  | { readonly status: "error"; readonly error: Error; readonly isRetrying: boolean };

export function useResearchSurveyReadiness(): {
  readonly state: ResearchSurveyReadinessLoadState;
  readonly reload: () => void;
} {
  const [version, setVersion] = useState(0);
  const [state, setState] = useState<ResearchSurveyReadinessLoadState>({ status: "loading" });
  useEffect(() => {
    const controller = new AbortController();
    void fetchResearchSurveyReadiness(controller.signal)
      .then((data) => setState({ status: "success", data }))
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setState({ status: "error", error: reason instanceof Error ? reason : new Error("核验原生 Survey runtime 失败"), isRetrying: false });
      });
    return () => controller.abort();
  }, [version]);
  return { state, reload: useCallback(() => setVersion((current) => current + 1), []) };
}
