import { useCallback, useEffect, useState } from "react";

import {
  fetchResearchProjects,
  type ResearchProjectsResponse,
} from "./researchProjectContracts";

export type ResearchProjectsLoadState =
  | { readonly status: "loading" }
  | { readonly status: "success"; readonly data: ResearchProjectsResponse }
  | { readonly status: "error"; readonly error: Error };

export function useResearchProjects(): {
  readonly state: ResearchProjectsLoadState;
  readonly reload: () => void;
} {
  const [version, setVersion] = useState(0);
  const [state, setState] = useState<ResearchProjectsLoadState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });
    void fetchResearchProjects(controller.signal)
      .then((data) => setState({ status: "success", data }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState({
          status: "error",
          error: error instanceof Error ? error : new Error("读取研究项目失败。"),
        });
      });
    return () => controller.abort();
  }, [version]);

  const reload = useCallback(() => setVersion((current) => current + 1), []);
  return { state, reload };
}

