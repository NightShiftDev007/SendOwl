import { useCallback, useEffect, useState } from "react";

import {
  fetchResearchRuns,
  type ResearchRunsResponse,
} from "./researchProjectContracts";

export type ResearchRunsLoadState =
  | { readonly status: "loading" }
  | { readonly status: "success"; readonly data: ResearchRunsResponse }
  | { readonly status: "error"; readonly error: Error };

export function useResearchRuns(projectId: string): {
  readonly state: ResearchRunsLoadState;
  readonly reload: () => void;
} {
  const [version, setVersion] = useState(0);
  const [state, setState] = useState<ResearchRunsLoadState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    let poll: number | undefined;
    const load = (): void => {
      void fetchResearchRuns(projectId, controller.signal)
        .then((data) => {
          setState({ status: "success", data });
          if (data.items.some((run) => run.status === "queued" || run.status === "running")) {
            poll = window.setTimeout(load, 2_000);
          }
        })
        .catch((error: unknown) => {
          if (error instanceof DOMException && error.name === "AbortError") return;
          setState({
            status: "error",
            error: error instanceof Error ? error : new Error("读取模拟运行失败。"),
          });
        });
    };
    setState({ status: "loading" });
    load();
    return () => {
      controller.abort();
      if (poll !== undefined) window.clearTimeout(poll);
    };
  }, [projectId, version]);

  const reload = useCallback(() => setVersion((current) => current + 1), []);
  return { state, reload };
}
