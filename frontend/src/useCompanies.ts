import { useCallback, useEffect, useRef, useState } from "react";

import { fetchCompanies, type CompaniesResponse } from "./companyContracts";

export type CompaniesLoadState =
  | { readonly status: "loading"; readonly data: CompaniesResponse | null }
  | { readonly status: "success"; readonly data: CompaniesResponse }
  | {
      readonly status: "error";
      readonly error: Error;
      readonly isRetrying: boolean;
      readonly data: CompaniesResponse | null;
    };

export interface UseCompaniesResult {
  readonly state: CompaniesLoadState;
  readonly reload: () => void;
}

function companiesData(state: CompaniesLoadState): CompaniesResponse | null {
  return state.data;
}

function normalizeCompaniesError(error: unknown): Error {
  return error instanceof Error
    ? error
    : new Error("读取企业档案失败：请求抛出了非标准错误。请检查浏览器控制台和后端日志。");
}

export function useCompanies(): UseCompaniesResult {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<CompaniesLoadState>({
    status: "loading",
    data: null,
  });
  const hasError = useRef<boolean>(false);

  useEffect(() => {
    const controller = new AbortController();

    setState((currentState) =>
      hasError.current && currentState.status === "error"
        ? { ...currentState, isRetrying: true }
        : { status: "loading", data: companiesData(currentState) },
    );

    void fetchCompanies(controller.signal)
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
          error: normalizeCompaniesError(error),
          isRetrying: false,
          data: companiesData(currentState),
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
