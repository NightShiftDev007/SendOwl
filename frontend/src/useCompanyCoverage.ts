import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchCompanyCoverage,
  type CompanyCoverageResponse,
} from "./companyContracts";

export type CompanyCoverageLoadState =
  | { readonly status: "idle" }
  | { readonly status: "loading"; readonly data: CompanyCoverageResponse | null }
  | { readonly status: "success"; readonly data: CompanyCoverageResponse }
  | {
      readonly status: "error";
      readonly error: Error;
      readonly isRetrying: boolean;
      readonly data: CompanyCoverageResponse | null;
    };

export interface UseCompanyCoverageResult {
  readonly state: CompanyCoverageLoadState;
  readonly reload: () => void;
}

function coverageData(
  state: CompanyCoverageLoadState,
  companyId: string,
): CompanyCoverageResponse | null {
  if (state.status === "idle" || state.data === null) {
    return null;
  }

  return state.data.company.id === companyId ? state.data : null;
}

function normalizeCoverageError(error: unknown): Error {
  return error instanceof Error
    ? error
    : new Error("读取企业名称命中候选失败：请求抛出了非标准错误。请检查浏览器控制台和后端日志。");
}

export function useCompanyCoverage(
  companyId: string | null,
  page: number,
  pageSize: number,
): UseCompanyCoverageResult {
  const [requestVersion, setRequestVersion] = useState<number>(0);
  const [state, setState] = useState<CompanyCoverageLoadState>({ status: "idle" });
  const hasError = useRef<boolean>(false);
  const previousCompanyId = useRef<string | null>(null);

  useEffect(() => {
    if (companyId === null) {
      hasError.current = false;
      previousCompanyId.current = null;
      setState({ status: "idle" });
      return;
    }

    if (previousCompanyId.current !== companyId) {
      hasError.current = false;
      previousCompanyId.current = companyId;
    }

    const controller = new AbortController();

    setState((currentState) =>
      hasError.current && currentState.status === "error"
        ? { ...currentState, isRetrying: true }
        : { status: "loading", data: coverageData(currentState, companyId) },
    );

    void fetchCompanyCoverage(companyId, page, pageSize, controller.signal)
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
          error: normalizeCoverageError(error),
          isRetrying: false,
          data: coverageData(currentState, companyId),
        }));
      });

    return () => {
      controller.abort();
    };
  }, [companyId, page, pageSize, requestVersion]);

  const reload = useCallback((): void => {
    setRequestVersion((currentVersion) => currentVersion + 1);
  }, []);

  return { state, reload };
}
