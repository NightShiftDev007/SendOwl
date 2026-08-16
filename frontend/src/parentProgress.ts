import { useCallback, useEffect, useRef, useState } from "react";
import { z } from "zod";

import { sha256DigestSchema } from "./mediaContracts";

export const parentProgressSchema = z.object({
  id: z.string().uuid(),
  status: z.enum(["queued", "running", "succeeded", "failed"]),
  observed_at: z.string().datetime({ offset: true }),
  attempt_number: z.number().int().min(1).max(5),
  trial_count: z.number().int().min(1).max(8),
  queued_trial_count: z.number().int().min(0).max(8),
  running_trial_count: z.number().int().min(0).max(8),
  succeeded_trial_count: z.number().int().min(0).max(8),
  failed_trial_count: z.number().int().min(0).max(8),
  event_count: z.number().int().nonnegative(),
  progress_sha256: sha256DigestSchema,
}).strict().superRefine((value, context) => {
  const total = value.queued_trial_count
    + value.running_trial_count
    + value.succeeded_trial_count
    + value.failed_trial_count;
  if (total !== value.trial_count) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["trial_count"],
      message: "Progress status counts must equal trial_count",
    });
  }
  const expectedStatus = value.queued_trial_count === value.trial_count
    ? "queued"
    : value.queued_trial_count > 0 || value.running_trial_count > 0
      ? "running"
      : value.succeeded_trial_count === value.trial_count
        ? "succeeded"
        : "failed";
  if (value.status !== expectedStatus) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["status"],
      message: "Progress status must match trial counts",
    });
  }
});

export type ParentProgress = z.infer<typeof parentProgressSchema>;

export type ProgressDrivenLoadState<T> =
  | { readonly status: "idle"; readonly data: null }
  | { readonly status: "loading"; readonly data: T | null }
  | { readonly status: "success"; readonly data: T }
  | {
      readonly status: "error";
      readonly error: Error;
      readonly isRetrying: boolean;
      readonly data: T | null;
    };

type ProgressLoader = (resourceId: string, signal: AbortSignal) => Promise<ParentProgress>;

function isActive(status: ParentProgress["status"]): boolean {
  return status === "queued" || status === "running";
}

function normalizedError(error: unknown, operation: string): Error {
  return error instanceof Error ? error : new Error(`${operation}失败：请求抛出了非标准错误。`);
}

export function useProgressDrivenResource<T extends { readonly status: ParentProgress["status"] }>(
  resourceId: string | null,
  detailLoader: (resourceId: string, signal: AbortSignal) => Promise<T>,
  progressLoader: ProgressLoader,
  pollMilliseconds: number,
  operation: string,
): { readonly state: ProgressDrivenLoadState<T>; readonly reload: () => void } {
  const [version, setVersion] = useState(0);
  const [state, setState] = useState<ProgressDrivenLoadState<T>>({
    status: resourceId === null ? "idle" : "loading",
    data: null,
  });
  const progressSha256 = useRef<string | null>(null);
  const previousId = useRef<string | null>(null);

  useEffect(() => {
    if (previousId.current !== resourceId) {
      previousId.current = resourceId;
      progressSha256.current = null;
    }
    if (resourceId === null) {
      setState({ status: "idle", data: null });
      return undefined;
    }
    const controller = new AbortController();
    setState((current) => ({ status: "loading", data: current.data }));
    void detailLoader(resourceId, controller.signal)
      .then((data) => setState({ status: "success", data }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState((current) => ({
          status: "error",
          error: normalizedError(error, operation),
          isRetrying: false,
          data: current.data,
        }));
      });
    return () => controller.abort();
  }, [detailLoader, operation, resourceId, version]);

  useEffect(() => {
    if (resourceId === null || state.status !== "success" || state.data === null
      || !isActive(state.data.status)) return undefined;
    const controller = new AbortController();
    let timer: number | null = null;
    const poll = (): void => {
      void progressLoader(resourceId, controller.signal)
        .then((progress) => {
          if (progress.id !== resourceId) {
            throw new Error("轻量进度不属于当前资源。");
          }
          const changed = progressSha256.current !== progress.progress_sha256;
          progressSha256.current = progress.progress_sha256;
          if (changed || !isActive(progress.status)) {
            setVersion((current) => current + 1);
            return;
          }
          timer = window.setTimeout(poll, pollMilliseconds);
        })
        .catch((error: unknown) => {
          if (error instanceof DOMException && error.name === "AbortError") return;
          setState((current) => ({
            status: "error",
            error: normalizedError(error, `${operation}进度`),
            isRetrying: false,
            data: current.data,
          }));
        });
    };
    timer = window.setTimeout(poll, pollMilliseconds);
    return () => {
      controller.abort();
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [operation, pollMilliseconds, progressLoader, resourceId, state]);

  return {
    state,
    reload: useCallback(() => {
      progressSha256.current = null;
      setVersion((current) => current + 1);
    }, []),
  };
}
