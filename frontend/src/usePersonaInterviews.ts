import { useCallback, useEffect, useState } from "react";

import {
  fetchPersonaInterviews,
  fetchPersonaInterviewSessions,
  type PersonaInterviewSessionsResponse,
  type PersonaInterviewsResponse,
} from "./personaInterviewContracts";

type PersonaInterviewsLoadState =
  | { readonly status: "idle"; readonly data: null }
  | { readonly status: "loading"; readonly data: PersonaInterviewsResponse | null }
  | { readonly status: "success"; readonly data: PersonaInterviewsResponse }
  | { readonly status: "error"; readonly error: Error; readonly data: PersonaInterviewsResponse | null };

export function usePersonaInterviews(reportId: string | null): {
  readonly state: PersonaInterviewsLoadState;
  readonly reload: () => void;
} {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<PersonaInterviewsLoadState>({ status: "idle", data: null });

  useEffect(() => {
    if (reportId === null) {
      setState({ status: "idle", data: null });
      return undefined;
    }
    const controller = new AbortController();
    let pollId: number | null = null;
    const load = (): void => {
      setState((current) => ({ status: "loading", data: current.data }));
      void fetchPersonaInterviews(reportId, controller.signal)
        .then((data) => {
          setState({ status: "success", data });
          if (data.items.some((item) => item.status === "queued" || item.status === "running")) {
            pollId = globalThis.setTimeout(load, 2_000);
          }
        })
        .catch((error: unknown) => {
          if (!(error instanceof DOMException && error.name === "AbortError")) {
            setState((current) => ({
              status: "error",
              error: error instanceof Error ? error : new Error("读取 Persona 访谈失败。"),
              data: current.data,
            }));
          }
        });
    };
    load();
    return () => {
      controller.abort();
      if (pollId !== null) globalThis.clearTimeout(pollId);
    };
  }, [reportId, requestVersion]);

  return {
    state,
    reload: useCallback((): void => setRequestVersion((current) => current + 1), []),
  };
}

type PersonaInterviewSessionsLoadState =
  | { readonly status: "idle"; readonly data: null }
  | { readonly status: "loading"; readonly data: PersonaInterviewSessionsResponse | null }
  | { readonly status: "success"; readonly data: PersonaInterviewSessionsResponse }
  | { readonly status: "error"; readonly error: Error; readonly data: PersonaInterviewSessionsResponse | null };

export function usePersonaInterviewSessions(reportId: string | null): {
  readonly state: PersonaInterviewSessionsLoadState;
  readonly reload: () => void;
} {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<PersonaInterviewSessionsLoadState>({ status: "idle", data: null });

  useEffect(() => {
    if (reportId === null) {
      setState({ status: "idle", data: null });
      return undefined;
    }
    const controller = new AbortController();
    let pollId: number | null = null;
    const load = (): void => {
      setState((current) => ({ status: "loading", data: current.data }));
      void fetchPersonaInterviewSessions(reportId, controller.signal)
        .then((data) => {
          setState({ status: "success", data });
          if (data.items.some((item) => item.status === "queued" || item.status === "running")) {
            pollId = globalThis.setTimeout(load, 2_000);
          }
        })
        .catch((error: unknown) => {
          if (!(error instanceof DOMException && error.name === "AbortError")) {
            setState((current) => ({
              status: "error",
              error: error instanceof Error ? error : new Error("读取多人访谈会话失败。"),
              data: current.data,
            }));
          }
        });
    };
    load();
    return () => {
      controller.abort();
      if (pollId !== null) globalThis.clearTimeout(pollId);
    };
  }, [reportId, requestVersion]);

  return {
    state,
    reload: useCallback((): void => setRequestVersion((current) => current + 1), []),
  };
}
