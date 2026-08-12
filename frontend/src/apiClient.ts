import { z } from "zod";

export type ApiFailureKind = "http" | "network" | "payload" | "timeout";

export class ApiRequestError extends Error {
  readonly endpoint: string;
  readonly kind: ApiFailureKind;
  readonly retryable: boolean;

  constructor(
    message: string,
    endpoint: string,
    kind: ApiFailureKind,
    retryable: boolean,
  ) {
    super(message);
    this.name = "ApiRequestError";
    this.endpoint = endpoint;
    this.kind = kind;
    this.retryable = retryable;
  }
}

export function isAmbiguousPostResultError(error: Error): boolean {
  return error instanceof ApiRequestError
    && (
      error.kind === "network"
      || error.kind === "timeout"
      || error.kind === "payload"
      || (error.kind === "http" && error.retryable)
    );
}

const maximumAttempts = 2;
const requestTimeoutMilliseconds = 8_000;
const retryDelayMilliseconds = 400;

interface TimedRequestSignal {
  readonly signal: AbortSignal;
  readonly didTimeout: () => boolean;
  readonly dispose: () => void;
}

function createAbortError(message: string): DOMException {
  return new DOMException(message, "AbortError");
}

function createTimedRequestSignal(parentSignal: AbortSignal): TimedRequestSignal {
  const controller = new AbortController();
  let timedOut = false;

  const abortFromParent = (): void => {
    controller.abort(parentSignal.reason);
  };

  if (parentSignal.aborted) {
    abortFromParent();
  } else {
    parentSignal.addEventListener("abort", abortFromParent, { once: true });
  }

  const timeoutId = globalThis.setTimeout((): void => {
    timedOut = true;
    controller.abort(
      new DOMException(
        `API request exceeded ${requestTimeoutMilliseconds}ms.`,
        "TimeoutError",
      ),
    );
  }, requestTimeoutMilliseconds);

  return {
    signal: controller.signal,
    didTimeout: (): boolean => timedOut,
    dispose: (): void => {
      globalThis.clearTimeout(timeoutId);
      parentSignal.removeEventListener("abort", abortFromParent);
    },
  };
}

function summarizeResponseBody(body: string): string {
  const normalizedBody = body.trim();

  return normalizedBody.length === 0
    ? "<empty response body>"
    : normalizedBody.slice(0, 800);
}

function parseJson<T>(
  body: string,
  endpoint: string,
  schema: z.ZodType<T, z.ZodTypeDef, unknown>,
): T {
  let payload: unknown;

  try {
    payload = JSON.parse(body);
  } catch (error: unknown) {
    const reason = error instanceof Error ? error.message : "unknown JSON parsing error";
    throw new ApiRequestError(
      `接口返回了无效 JSON。endpoint=${endpoint}; reason=${reason}; body=${summarizeResponseBody(body)}`,
      endpoint,
      "payload",
      false,
    );
  }

  const result = schema.safeParse(payload);

  if (!result.success) {
    throw new ApiRequestError(
      `接口契约校验失败。endpoint=${endpoint}; issues=${result.error.issues
        .map((issue) => `${issue.path.join(".") || "response"}: ${issue.message}`)
        .join("; ")}`,
      endpoint,
      "payload",
      false,
    );
  }

  return result.data;
}

async function waitBeforeRetry(signal: AbortSignal): Promise<void> {
  if (signal.aborted) {
    throw createAbortError("API 请求已取消。");
  }

  await new Promise<void>((resolve, reject) => {
    const finish = (): void => {
      signal.removeEventListener("abort", abort);
      resolve();
    };
    const abort = (): void => {
      globalThis.clearTimeout(timeoutId);
      signal.removeEventListener("abort", abort);
      reject(createAbortError("API 请求已取消。"));
    };
    const timeoutId = globalThis.setTimeout(finish, retryDelayMilliseconds);

    signal.addEventListener("abort", abort, { once: true });
  });
}

async function getJsonOnce<T>(
  endpoint: string,
  schema: z.ZodType<T, z.ZodTypeDef, unknown>,
  parentSignal: AbortSignal,
): Promise<T> {
  let response: Response;
  let body: string;
  const timedSignal = createTimedRequestSignal(parentSignal);

  try {
    response = await fetch(endpoint, {
      headers: { Accept: "application/json" },
      signal: timedSignal.signal,
    });
    body = await response.text();
  } catch (error: unknown) {
    if (parentSignal.aborted) {
      throw createAbortError("API 请求已取消。");
    }

    if (timedSignal.didTimeout()) {
      throw new ApiRequestError(
        `接口请求超时。endpoint=${endpoint}; timeout_ms=${requestTimeoutMilliseconds}`,
        endpoint,
        "timeout",
        true,
      );
    }

    const reason = error instanceof Error ? error.message : "unknown network error";
    throw new ApiRequestError(
      `无法连接后端接口。endpoint=${endpoint}; reason=${reason}`,
      endpoint,
      "network",
      true,
    );
  } finally {
    timedSignal.dispose();
  }

  if (!response.ok) {
    throw new ApiRequestError(
      `后端拒绝了接口请求。endpoint=${endpoint}; status=${response.status} ${response.statusText}; body=${summarizeResponseBody(body)}`,
      endpoint,
      "http",
      response.status >= 500,
    );
  }

  return parseJson(body, endpoint, schema);
}

async function postJsonOnce<TRequest extends object, TResponse>(
  endpoint: string,
  requestBody: TRequest,
  schema: z.ZodType<TResponse, z.ZodTypeDef, unknown>,
  parentSignal: AbortSignal,
): Promise<TResponse> {
  let serializedBody: string;

  try {
    serializedBody = JSON.stringify(requestBody);
  } catch (error: unknown) {
    const reason = error instanceof Error ? error.message : "unknown JSON serialization error";
    throw new ApiRequestError(
      `无法序列化接口请求。endpoint=${endpoint}; reason=${reason}`,
      endpoint,
      "payload",
      false,
    );
  }

  let response: Response;
  let body: string;
  const timedSignal = createTimedRequestSignal(parentSignal);

  try {
    response = await fetch(endpoint, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: serializedBody,
      signal: timedSignal.signal,
    });
    body = await response.text();
  } catch (error: unknown) {
    if (parentSignal.aborted) {
      throw createAbortError("API 请求已取消。");
    }

    if (timedSignal.didTimeout()) {
      throw new ApiRequestError(
        `接口请求超时。endpoint=${endpoint}; timeout_ms=${requestTimeoutMilliseconds}`,
        endpoint,
        "timeout",
        false,
      );
    }

    const reason = error instanceof Error ? error.message : "unknown network error";
    throw new ApiRequestError(
      `无法连接后端接口。endpoint=${endpoint}; reason=${reason}`,
      endpoint,
      "network",
      false,
    );
  } finally {
    timedSignal.dispose();
  }

  if (!response.ok) {
    throw new ApiRequestError(
      `后端拒绝了接口请求。endpoint=${endpoint}; status=${response.status} ${response.statusText}; body=${summarizeResponseBody(body)}`,
      endpoint,
      "http",
      response.status >= 500,
    );
  }

  return parseJson(body, endpoint, schema);
}

export async function getJson<T>(
  endpoint: string,
  schema: z.ZodType<T, z.ZodTypeDef, unknown>,
  signal: AbortSignal,
): Promise<T> {
  let lastError: ApiRequestError | undefined;

  for (let attempt = 1; attempt <= maximumAttempts; attempt += 1) {
    try {
      return await getJsonOnce(endpoint, schema, signal);
    } catch (error: unknown) {
      if (error instanceof DOMException && error.name === "AbortError") {
        throw error;
      }

      const reason = error instanceof Error ? error.message : "request threw a non-standard error";
      const requestError =
        error instanceof ApiRequestError
          ? error
          : new ApiRequestError(
              `接口请求发生未知错误。endpoint=${endpoint}; reason=${reason}`,
              endpoint,
              "network",
              true,
            );
      lastError = requestError;

      if (!requestError.retryable || attempt === maximumAttempts) {
        throw requestError;
      }

      console.warn("API request failed; retrying", {
        attempt,
        delayMilliseconds: retryDelayMilliseconds,
        endpoint,
        kind: requestError.kind,
        reason: requestError.message,
      });
      await waitBeforeRetry(signal);
    }
  }

  throw new ApiRequestError(
    `接口请求失败。endpoint=${endpoint}; reason=${lastError?.message ?? "request loop ended unexpectedly"}`,
    endpoint,
    "network",
    false,
  );
}

export function postJson<TRequest extends object, TResponse>(
  endpoint: string,
  requestBody: TRequest,
  schema: z.ZodType<TResponse, z.ZodTypeDef, unknown>,
  signal: AbortSignal,
): Promise<TResponse> {
  return postJsonOnce(endpoint, requestBody, schema, signal);
}
