import type { SurveyTrial } from "./surveyContracts";

export type SurveyTrialSelection =
  | { readonly status: "idle" }
  | { readonly status: "selected"; readonly trial: SurveyTrial }
  | { readonly status: "invalid"; readonly trialId: string };

export function resolveSurveyTrialSelection(
  trials: readonly SurveyTrial[],
  trialId: string | null,
): SurveyTrialSelection {
  if (trialId === null) return { status: "idle" };
  const trial = trials.find((item) => item.id === trialId);
  return trial === undefined
    ? { status: "invalid", trialId }
    : { status: "selected", trial };
}
