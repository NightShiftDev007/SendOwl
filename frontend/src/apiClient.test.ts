import { afterEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";

import {
  ApiRequestError,
  isAmbiguousPostResultError,
  postJson,
} from "./apiClient";

const responseSchema = z.object({ id: z.string().uuid() }).strict();

afterEach(() => {
  vi.restoreAllMocks();
});

describe("POST result ambiguity", () => {
  it("marks HTTP 5xx as ambiguous metadata without retrying the POST", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response('{"detail":"failed after commit"}', {
        status: 500,
        statusText: "Internal Server Error",
      }),
    );
    let receivedError: unknown;

    try {
      await postJson(
        "/api/v2/test",
        { value: "request" },
        responseSchema,
        new AbortController().signal,
      );
    } catch (error: unknown) {
      receivedError = error;
    }

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(receivedError).toBeInstanceOf(ApiRequestError);

    if (!(receivedError instanceof ApiRequestError)) {
      throw new Error("POST 500 did not raise ApiRequestError");
    }

    expect(receivedError.kind).toBe("http");
    expect(receivedError.retryable).toBe(true);
    expect(isAmbiguousPostResultError(receivedError)).toBe(true);
  });

  it("treats an invalid success payload as ambiguous but keeps HTTP 4xx explicit", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response('{"id":"not-a-uuid"}', { status: 202 }),
    );
    let payloadError: unknown;

    try {
      await postJson(
        "/api/v2/test",
        { value: "request" },
        responseSchema,
        new AbortController().signal,
      );
    } catch (error: unknown) {
      payloadError = error;
    }

    expect(payloadError).toBeInstanceOf(ApiRequestError);

    if (!(payloadError instanceof ApiRequestError)) {
      throw new Error("invalid POST response did not raise ApiRequestError");
    }

    expect(payloadError.kind).toBe("payload");
    expect(isAmbiguousPostResultError(payloadError)).toBe(true);
    expect(
      isAmbiguousPostResultError(
        new ApiRequestError("request rejected", "/api/v2/test", "http", false),
      ),
    ).toBe(false);
  });
});
