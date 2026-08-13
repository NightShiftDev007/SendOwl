import { z } from "zod";

const runStudioModeSchema = z.enum(["platform", "semantic"]);
const runStudioPanelSchema = z.enum(["timeline", "metrics", "provenance"]);
const identifierSchema = z.string().uuid();
const allowedParameterNames = new Set([
  "mode",
  "cohort_id",
  "scenario_id",
  "experiment_id",
  "trial_id",
  "panel",
]);

export type RunStudioMode = z.infer<typeof runStudioModeSchema>;
export type RunStudioPanel = z.infer<typeof runStudioPanelSchema>;

export interface RunStudioRoute {
  readonly mode: RunStudioMode;
  readonly cohortId: string | null;
  readonly scenarioId: string | null;
  readonly experimentId: string | null;
  readonly trialId: string | null;
  readonly panel: RunStudioPanel | null;
}

export type RunStudioRouteResult =
  | { readonly status: "resolved"; readonly route: RunStudioRoute }
  | { readonly status: "invalid"; readonly message: string };

function singleParameter(
  parameters: URLSearchParams,
  name: string,
): string | null {
  const values = parameters.getAll(name);

  if (values.length > 1) {
    throw new Error(`参数“${name}”不能重复。`);
  }

  return values[0] ?? null;
}

function parseOptionalIdentifier(value: string | null, name: string): string | null {
  if (value === null) {
    return null;
  }

  const result = identifierSchema.safeParse(value);

  if (!result.success) {
    throw new Error(`参数“${name}”必须是合法 UUID。`);
  }

  return result.data;
}

export function resolveRunStudioRoute(query: string): RunStudioRouteResult {
  const parameters = new URLSearchParams(query);

  for (const name of parameters.keys()) {
    if (!allowedParameterNames.has(name)) {
      return {
        status: "invalid",
        message: `Run Studio 不支持查询参数“${name}”。`,
      };
    }
  }

  try {
    const modeValue = singleParameter(parameters, "mode");
    const modeResult = runStudioModeSchema.safeParse(modeValue ?? "platform");

    if (!modeResult.success) {
      return {
        status: "invalid",
        message: "参数“mode”只能是 platform 或 semantic。",
      };
    }

    const experimentId = parseOptionalIdentifier(
      singleParameter(parameters, "experiment_id"),
      "experiment_id",
    );
    const cohortId = parseOptionalIdentifier(
      singleParameter(parameters, "cohort_id"),
      "cohort_id",
    );
    const scenarioId = parseOptionalIdentifier(
      singleParameter(parameters, "scenario_id"),
      "scenario_id",
    );
    const trialId = parseOptionalIdentifier(
      singleParameter(parameters, "trial_id"),
      "trial_id",
    );
    const panelValue = singleParameter(parameters, "panel");
    const panelResult = panelValue === null
      ? null
      : runStudioPanelSchema.safeParse(panelValue);

    if (panelResult !== null && !panelResult.success) {
      return {
        status: "invalid",
        message: "参数“panel”只能是 timeline、metrics 或 provenance。",
      };
    }

    if (modeResult.data === "platform"
      && (cohortId !== null
        || scenarioId !== null
        || experimentId !== null
        || trialId !== null
        || panelResult !== null)) {
      return {
        status: "invalid",
        message: "cohort_id、scenario_id、experiment_id、trial_id 和 panel 只属于 semantic 模式。",
      };
    }

    if (trialId !== null && experimentId === null) {
      return {
        status: "invalid",
        message: "trial_id 必须与所属 experiment_id 一起提供。",
      };
    }

    return {
      status: "resolved",
      route: {
        mode: modeResult.data,
        cohortId,
        scenarioId,
        experimentId,
        trialId,
        panel: panelResult?.data ?? null,
      },
    };
  } catch (error: unknown) {
    return {
      status: "invalid",
      message: error instanceof Error
        ? error.message
        : "Run Studio 查询参数解析失败。",
    };
  }
}

export function createRunStudioHash(route: RunStudioRoute): string {
  if (route.mode === "platform"
    && (route.cohortId !== null
      || route.scenarioId !== null
      || route.experimentId !== null
      || route.trialId !== null
      || route.panel !== null)) {
    throw new Error("Platform mode cannot serialize semantic experiment state.");
  }

  if (route.trialId !== null && route.experimentId === null) {
    throw new Error("A Trial route requires its parent experiment identifier.");
  }

  const parameters = new URLSearchParams({ mode: route.mode });

  if (route.cohortId !== null) {
    parameters.set("cohort_id", identifierSchema.parse(route.cohortId));
  }

  if (route.scenarioId !== null) {
    parameters.set("scenario_id", identifierSchema.parse(route.scenarioId));
  }

  if (route.experimentId !== null) {
    parameters.set("experiment_id", identifierSchema.parse(route.experimentId));
  }

  if (route.trialId !== null) {
    parameters.set("trial_id", identifierSchema.parse(route.trialId));
  }

  if (route.panel !== null) {
    parameters.set("panel", runStudioPanelSchema.parse(route.panel));
  }

  return `#/runs?${parameters.toString()}`;
}
