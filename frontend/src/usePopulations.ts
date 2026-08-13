import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchCohortDetail,
  fetchCohorts,
  fetchPopulationDatasets,
  fetchPopulationPersonas,
  type CohortDetail,
  type CohortsResponse,
  type PopulationDatasetsResponse,
  type PopulationPersonasResponse,
} from "./populationContracts";

export type PopulationDatasetsLoadState =
  | { readonly status: "loading"; readonly data: PopulationDatasetsResponse | null }
  | { readonly status: "success"; readonly data: PopulationDatasetsResponse }
  | {
      readonly status: "error";
      readonly error: Error;
      readonly isRetrying: boolean;
      readonly data: PopulationDatasetsResponse | null;
    };

export type PopulationPersonasLoadState =
  | { readonly status: "idle" }
  | { readonly status: "loading"; readonly data: PopulationPersonasResponse | null }
  | { readonly status: "success"; readonly data: PopulationPersonasResponse }
  | {
      readonly status: "error";
      readonly error: Error;
      readonly isRetrying: boolean;
      readonly data: PopulationPersonasResponse | null;
    };

export type CohortsLoadState =
  | { readonly status: "loading"; readonly data: CohortsResponse | null }
  | { readonly status: "success"; readonly data: CohortsResponse }
  | {
      readonly status: "error";
      readonly error: Error;
      readonly isRetrying: boolean;
      readonly data: CohortsResponse | null;
    };

export type CohortDetailLoadState =
  | { readonly status: "idle" }
  | { readonly status: "loading"; readonly data: CohortDetail | null }
  | { readonly status: "success"; readonly data: CohortDetail }
  | {
      readonly status: "error";
      readonly error: Error;
      readonly isRetrying: boolean;
      readonly data: CohortDetail | null;
    };

export interface UsePopulationDatasetsResult {
  readonly state: PopulationDatasetsLoadState;
  readonly reload: () => void;
}

export interface UsePopulationPersonasResult {
  readonly state: PopulationPersonasLoadState;
  readonly reload: () => void;
}

export interface UseCohortsResult {
  readonly state: CohortsLoadState;
  readonly reload: () => void;
}

export interface UseCohortDetailResult {
  readonly state: CohortDetailLoadState;
  readonly reload: () => void;
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function normalizeDatasetsError(error: unknown): Error {
  return error instanceof Error
    ? error
    : new Error("读取 Persona 数据集失败：请求抛出了非标准错误。请检查后端日志。");
}

function normalizePersonasError(error: unknown): Error {
  return error instanceof Error
    ? error
    : new Error("读取 Persona 列表失败：请求抛出了非标准错误。请检查后端日志。");
}

function normalizeCohortsError(error: unknown): Error {
  return error instanceof Error
    ? error
    : new Error("读取冻结 Cohort 失败：请求抛出了非标准错误。请检查后端日志。");
}

function normalizeCohortDetailError(error: unknown): Error {
  return error instanceof Error
    ? error
    : new Error("读取 Cohort 成员失败：请求抛出了非标准错误。请检查后端日志。");
}

function datasetsData(
  state: PopulationDatasetsLoadState,
): PopulationDatasetsResponse | null {
  return state.data;
}

function personasData(
  state: PopulationPersonasLoadState,
): PopulationPersonasResponse | null {
  return state.status === "idle" ? null : state.data;
}

function cohortsData(state: CohortsLoadState): CohortsResponse | null {
  return state.data;
}

function cohortDetailData(
  state: CohortDetailLoadState,
  cohortId: string,
): CohortDetail | null {
  if (state.status === "idle" || state.data === null) {
    return null;
  }

  return state.data.id === cohortId ? state.data : null;
}

export function usePopulationDatasets(): UsePopulationDatasetsResult {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<PopulationDatasetsLoadState>({
    status: "loading",
    data: null,
  });
  const hasError = useRef<boolean>(false);

  useEffect(() => {
    const controller = new AbortController();

    setState((currentState) =>
      hasError.current && currentState.status === "error"
        ? { ...currentState, isRetrying: true }
        : { status: "loading", data: datasetsData(currentState) },
    );

    void fetchPopulationDatasets(controller.signal)
      .then((data) => {
        hasError.current = false;
        setState({ status: "success", data });
      })
      .catch((error: unknown) => {
        if (isAbortError(error)) {
          return;
        }

        hasError.current = true;
        setState((currentState) => ({
          status: "error",
          error: normalizeDatasetsError(error),
          isRetrying: false,
          data: datasetsData(currentState),
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

export function usePopulationPersonas(
  datasetId: string | null,
  query: string | null,
  page: number,
  pageSize: number,
): UsePopulationPersonasResult {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<PopulationPersonasLoadState>({ status: "idle" });
  const hasError = useRef<boolean>(false);
  const previousRequestKey = useRef<string | null>(null);

  useEffect(() => {
    if (datasetId === null) {
      hasError.current = false;
      previousRequestKey.current = null;
      setState({ status: "idle" });
      return;
    }

    const requestKey = `${datasetId}:${query ?? ""}:${page}:${pageSize}`;
    const isNewRequest = previousRequestKey.current !== requestKey;

    if (isNewRequest) {
      hasError.current = false;
      previousRequestKey.current = requestKey;
    }

    const controller = new AbortController();

    setState((currentState) =>
      hasError.current && currentState.status === "error"
        ? { ...currentState, isRetrying: true }
        : {
            status: "loading",
            data: isNewRequest ? null : personasData(currentState),
          },
    );

    void fetchPopulationPersonas(
      datasetId,
      { q: query, page, pageSize },
      controller.signal,
    )
      .then((data) => {
        hasError.current = false;
        setState({ status: "success", data });
      })
      .catch((error: unknown) => {
        if (isAbortError(error)) {
          return;
        }

        hasError.current = true;
        setState((currentState) => ({
          status: "error",
          error: normalizePersonasError(error),
          isRetrying: false,
          data: personasData(currentState),
        }));
      });

    return () => {
      controller.abort();
    };
  }, [datasetId, page, pageSize, query, requestVersion]);

  const reload = useCallback((): void => {
    setRequestVersion((currentVersion) => currentVersion + 1);
  }, []);

  return { state, reload };
}

export function useCohorts(): UseCohortsResult {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<CohortsLoadState>({
    status: "loading",
    data: null,
  });
  const hasError = useRef<boolean>(false);

  useEffect(() => {
    const controller = new AbortController();

    setState((currentState) =>
      hasError.current && currentState.status === "error"
        ? { ...currentState, isRetrying: true }
        : { status: "loading", data: cohortsData(currentState) },
    );

    void fetchCohorts(controller.signal)
      .then((data) => {
        hasError.current = false;
        setState({ status: "success", data });
      })
      .catch((error: unknown) => {
        if (isAbortError(error)) {
          return;
        }

        hasError.current = true;
        setState((currentState) => ({
          status: "error",
          error: normalizeCohortsError(error),
          isRetrying: false,
          data: cohortsData(currentState),
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

export function useCohortDetail(cohortId: string | null): UseCohortDetailResult {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<CohortDetailLoadState>({ status: "idle" });
  const hasError = useRef<boolean>(false);
  const previousCohortId = useRef<string | null>(null);

  useEffect(() => {
    if (cohortId === null) {
      hasError.current = false;
      previousCohortId.current = null;
      setState({ status: "idle" });
      return;
    }

    const isNewCohort = previousCohortId.current !== cohortId;

    if (isNewCohort) {
      hasError.current = false;
      previousCohortId.current = cohortId;
    }

    const controller = new AbortController();

    setState((currentState) =>
      hasError.current && currentState.status === "error"
        ? { ...currentState, isRetrying: true }
        : {
            status: "loading",
            data: isNewCohort ? null : cohortDetailData(currentState, cohortId),
          },
    );

    void fetchCohortDetail(cohortId, controller.signal)
      .then((data) => {
        hasError.current = false;
        setState({ status: "success", data });
      })
      .catch((error: unknown) => {
        if (isAbortError(error)) {
          return;
        }

        hasError.current = true;
        setState((currentState) => ({
          status: "error",
          error: normalizeCohortDetailError(error),
          isRetrying: false,
          data: cohortDetailData(currentState, cohortId),
        }));
      });

    return () => {
      controller.abort();
    };
  }, [cohortId, requestVersion]);

  const reload = useCallback((): void => {
    setRequestVersion((currentVersion) => currentVersion + 1);
  }, []);

  return { state, reload };
}
