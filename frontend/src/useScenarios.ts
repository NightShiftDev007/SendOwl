import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchScenarioDetail,
  fetchScenarios,
  type ScenarioDetail,
  type ScenariosResponse,
} from "./scenarioContracts";

export type ScenariosLoadState =
  | { readonly status: "loading"; readonly data: ScenariosResponse | null }
  | { readonly status: "success"; readonly data: ScenariosResponse }
  | {
      readonly status: "error";
      readonly error: Error;
      readonly isRetrying: boolean;
      readonly data: ScenariosResponse | null;
    };

export type ScenarioDetailLoadState =
  | { readonly status: "idle" }
  | { readonly status: "loading"; readonly data: ScenarioDetail | null }
  | { readonly status: "success"; readonly data: ScenarioDetail }
  | {
      readonly status: "error";
      readonly error: Error;
      readonly isRetrying: boolean;
      readonly data: ScenarioDetail | null;
    };

export interface UseScenariosResult {
  readonly state: ScenariosLoadState;
  readonly reload: () => void;
}

export interface UseScenarioDetailResult {
  readonly state: ScenarioDetailLoadState;
  readonly reload: () => void;
}

function normalizeScenariosError(error: unknown): Error {
  return error instanceof Error
    ? error
    : new Error("读取决策实验失败：请求抛出了非标准错误。请检查浏览器控制台和后端日志。");
}

function normalizeScenarioDetailError(error: unknown): Error {
  return error instanceof Error
    ? error
    : new Error("读取实验规格失败：请求抛出了非标准错误。请检查浏览器控制台和后端日志。");
}

function scenariosData(state: ScenariosLoadState): ScenariosResponse | null {
  return state.data;
}

function scenarioDetailData(
  state: ScenarioDetailLoadState,
  scenarioId: string,
): ScenarioDetail | null {
  if (state.status === "idle" || state.data === null) {
    return null;
  }

  return state.data.id === scenarioId ? state.data : null;
}

export function useScenarios(): UseScenariosResult {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<ScenariosLoadState>({
    status: "loading",
    data: null,
  });
  const hasError = useRef<boolean>(false);

  useEffect(() => {
    const controller = new AbortController();

    setState((currentState) =>
      hasError.current && currentState.status === "error"
        ? { ...currentState, isRetrying: true }
        : { status: "loading", data: scenariosData(currentState) },
    );

    void fetchScenarios(controller.signal)
      .then((data) => {
        hasError.current = false;
        setState({ status: "success", data });
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }

        hasError.current = true;
        setState((currentState) => ({
          status: "error",
          error: normalizeScenariosError(error),
          isRetrying: false,
          data: scenariosData(currentState),
        }));
      });

    return () => {
      controller.abort();
    };
  }, [requestVersion]);

  const reload = useCallback((): void => {
    setRequestVersion((currentVersion) => currentVersion + 1);
  }, []);

  return { state, reload };
}

export function useScenarioDetail(scenarioId: string | null): UseScenarioDetailResult {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<ScenarioDetailLoadState>({ status: "idle" });
  const hasError = useRef<boolean>(false);
  const previousScenarioId = useRef<string | null>(null);

  useEffect(() => {
    if (scenarioId === null) {
      hasError.current = false;
      previousScenarioId.current = null;
      setState({ status: "idle" });
      return;
    }

    if (previousScenarioId.current !== scenarioId) {
      hasError.current = false;
      previousScenarioId.current = scenarioId;
    }

    const controller = new AbortController();

    setState((currentState) =>
      hasError.current && currentState.status === "error"
        ? { ...currentState, isRetrying: true }
        : {
            status: "loading",
            data: scenarioDetailData(currentState, scenarioId),
          },
    );

    void fetchScenarioDetail(scenarioId, controller.signal)
      .then((data) => {
        hasError.current = false;
        setState({ status: "success", data });
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }

        hasError.current = true;
        setState((currentState) => ({
          status: "error",
          error: normalizeScenarioDetailError(error),
          isRetrying: false,
          data: scenarioDetailData(currentState, scenarioId),
        }));
      });

    return () => {
      controller.abort();
    };
  }, [requestVersion, scenarioId]);

  const reload = useCallback((): void => {
    setRequestVersion((currentVersion) => currentVersion + 1);
  }, []);

  return { state, reload };
}
