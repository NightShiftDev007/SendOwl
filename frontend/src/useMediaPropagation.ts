import { useEffect, useState } from "react";

import {
  fetchMediaPropagation,
  type MediaPropagationResponse,
} from "./mediaContracts";

export type MediaPropagationLoadState =
  | { readonly status: "loading" }
  | { readonly status: "success"; readonly data: MediaPropagationResponse }
  | { readonly status: "error"; readonly error: Error };

export function useMediaPropagation(): MediaPropagationLoadState {
  const [state, setState] = useState<MediaPropagationLoadState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    void fetchMediaPropagation(controller.signal)
      .then((data) => setState({ status: "success", data }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") {
          return;
        }
        setState({
          status: "error",
          error: error instanceof Error ? error : new Error("传播链接口返回了非标准错误。"),
        });
      });
    return () => controller.abort();
  }, []);

  return state;
}
