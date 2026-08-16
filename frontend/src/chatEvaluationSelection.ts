import type { ChatTrial } from "./chatEvaluationContracts";

export type ChatTrialSelection =
  | { readonly status: "idle" }
  | { readonly status: "selected"; readonly trial: ChatTrial }
  | { readonly status: "invalid"; readonly trialId: string };

export function resolveChatTrialSelection(
  trials: readonly ChatTrial[],
  trialId: string | null,
): ChatTrialSelection {
  if (trialId === null) return { status: "idle" };
  const trial = trials.find((item) => item.id === trialId);
  return trial === undefined
    ? { status: "invalid", trialId }
    : { status: "selected", trial };
}
