import { z } from "zod";

const identifierSchema = z.string().uuid();
const allowedParameterNames = new Set(["project_id", "run_id", "experiment_id", "legacy"]);

export type ReportWorkspaceRoute =
  | { readonly mode: "native"; readonly projectId: string | null; readonly runId: string | null }
  | { readonly mode: "legacy"; readonly experimentId: string | null };

export type ReportWorkspaceRouteResult =
  | { readonly status: "resolved"; readonly route: ReportWorkspaceRoute }
  | { readonly status: "invalid"; readonly message: string };

function singleParameter(parameters: URLSearchParams, name: string): string | null {
  const values = parameters.getAll(name);
  if (values.length > 1) throw new Error(`报告工作区的 ${name} 参数不能重复。`);
  return values[0] ?? null;
}

function optionalIdentifier(value: string | null, name: string): string | null {
  if (value === null) return null;
  const result = identifierSchema.safeParse(value);
  if (!result.success) throw new Error(`${name} 必须是有效 UUID。`);
  return result.data;
}

export function resolveReportWorkspaceRoute(query: string): ReportWorkspaceRouteResult {
  const parameters = new URLSearchParams(query);
  for (const name of parameters.keys()) {
    if (!allowedParameterNames.has(name)) {
      return { status: "invalid", message: `报告工作区不支持查询参数“${name}”。` };
    }
  }
  try {
    const projectId = optionalIdentifier(singleParameter(parameters, "project_id"), "project_id");
    const runId = optionalIdentifier(singleParameter(parameters, "run_id"), "run_id");
    const experimentId = optionalIdentifier(singleParameter(parameters, "experiment_id"), "experiment_id");
    const legacy = singleParameter(parameters, "legacy");
    if (legacy !== null && legacy !== "1") {
      return { status: "invalid", message: "legacy 只接受值 1。" };
    }
    if ((projectId === null) !== (runId === null)) {
      return { status: "invalid", message: "project_id 与 run_id 必须同时提供。" };
    }
    const requestsLegacy = legacy === "1" || experimentId !== null;
    if (requestsLegacy && (projectId !== null || runId !== null)) {
      return { status: "invalid", message: "原生报告参数不能与历史报告参数混用。" };
    }
    return requestsLegacy
      ? { status: "resolved", route: { mode: "legacy", experimentId } }
      : { status: "resolved", route: { mode: "native", projectId, runId } };
  } catch (error: unknown) {
    return {
      status: "invalid",
      message: error instanceof Error ? error.message : "报告工作区查询参数解析失败。",
    };
  }
}

export function createNativeReportHash(projectId: string, runId: string): string {
  const parameters = new URLSearchParams({
    project_id: identifierSchema.parse(projectId),
    run_id: identifierSchema.parse(runId),
  });
  return `#/reports?${parameters.toString()}`;
}

export function createLegacyReportHash(experimentId: string | null): string {
  const parameters = new URLSearchParams({ legacy: "1" });
  if (experimentId !== null) parameters.set("experiment_id", identifierSchema.parse(experimentId));
  return `#/reports?${parameters.toString()}`;
}
