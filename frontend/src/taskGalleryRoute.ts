import { z } from "zod";

const taskKindSchema = z.enum(["survey", "chat", "web", "linux", "trials", "batch"]);
const archiveKindSchema = z.enum(["survey", "chat", "web", "linux"]);
const archiveStatusSchema = z.enum(["queued", "running", "succeeded", "failed"]);
const identifierSchema = z.string().uuid();
const positivePageSchema = z.coerce.number().int().positive();
const allowedParameterNames = new Set([
  "task",
  "experiment_id",
  "evaluation_id",
  "trial_id",
  "registry_id",
  "kind",
  "status",
  "page",
]);

export interface TaskGalleryRoute {
  readonly task: z.infer<typeof taskKindSchema> | null;
  readonly experimentId: string | null;
  readonly evaluationId: string | null;
  readonly trialId: string | null;
  readonly registryId: string | null;
  readonly archiveKind: z.infer<typeof archiveKindSchema> | null;
  readonly archiveStatus: z.infer<typeof archiveStatusSchema> | null;
  readonly page: number | null;
}

export type TaskGalleryRouteResult =
  | { readonly status: "resolved"; readonly route: TaskGalleryRoute }
  | { readonly status: "invalid"; readonly message: string };

function singleParameter(parameters: URLSearchParams, name: string): string | null {
  const values = parameters.getAll(name);
  if (values.length > 1) {
    throw new Error(`Task Gallery 的 ${name} 参数不能重复。`);
  }
  return values[0] ?? null;
}

function optionalIdentifier(value: string | null, name: string): string | null {
  if (value === null) return null;
  const result = identifierSchema.safeParse(value);
  if (!result.success) throw new Error(`${name} 必须是有效 UUID。`);
  return result.data;
}

export function resolveTaskGalleryRoute(query: string): TaskGalleryRouteResult {
  const parameters = new URLSearchParams(query);
  for (const name of parameters.keys()) {
    if (!allowedParameterNames.has(name)) {
      return {
        status: "invalid",
        message: `Task Gallery 不支持查询参数“${name}”。`,
      };
    }
  }

  try {
    const rawTask = singleParameter(parameters, "task");
    const taskResult = rawTask === null ? null : taskKindSchema.safeParse(rawTask);
    if (taskResult !== null && !taskResult.success) {
      return {
        status: "invalid",
        message: `Task Gallery 中不存在任务“${rawTask ?? ""}”。`,
      };
    }

    const task = taskResult?.data ?? null;
    const experimentId = optionalIdentifier(
      singleParameter(parameters, "experiment_id"),
      "experiment_id",
    );
    const evaluationId = optionalIdentifier(
      singleParameter(parameters, "evaluation_id"),
      "evaluation_id",
    );
    const trialId = optionalIdentifier(singleParameter(parameters, "trial_id"), "trial_id");
    const registryId = optionalIdentifier(singleParameter(parameters, "registry_id"), "registry_id");
    const rawKind = singleParameter(parameters, "kind");
    const kindResult = rawKind === null ? null : archiveKindSchema.safeParse(rawKind);
    if (kindResult !== null && !kindResult.success) {
      return { status: "invalid", message: "kind 只能是 survey、chat、web 或 linux。" };
    }
    const rawStatus = singleParameter(parameters, "status");
    const statusResult = rawStatus === null ? null : archiveStatusSchema.safeParse(rawStatus);
    if (statusResult !== null && !statusResult.success) {
      return {
        status: "invalid",
        message: "status 只能是 queued、running、succeeded 或 failed。",
      };
    }
    const rawPage = singleParameter(parameters, "page");
    const pageResult = rawPage === null ? null : positivePageSchema.safeParse(rawPage);
    if (pageResult !== null && !pageResult.success) {
      return { status: "invalid", message: "page 必须是正整数。" };
    }

    if (task !== "survey" && experimentId !== null) {
      return {
        status: "invalid",
        message: "experiment_id 只属于 Survey Playground。",
      };
    }
    if (task !== "chat" && task !== "web" && task !== "linux" && evaluationId !== null) {
      return {
        status: "invalid",
        message: "evaluation_id 只属于 Chat、Web 或 Linux Evaluation。",
      };
    }
    if (task === "survey" && trialId !== null && experimentId === null) {
      return { status: "invalid", message: "Survey trial_id 必须与 experiment_id 一起提供。" };
    }
    if ((task === "chat" || task === "web") && trialId !== null && evaluationId === null) {
      return { status: "invalid", message: "Chat trial_id 必须与 evaluation_id 一起提供。" };
    }
    if (task !== "survey" && task !== "chat" && task !== "web" && task !== "linux" && trialId !== null) {
      return { status: "invalid", message: "trial_id 只属于 Survey 或 Chat 详情。" };
    }
    if (task !== "batch" && registryId !== null) {
      return { status: "invalid", message: "registry_id 只属于 Batch Registry。" };
    }

    if (task !== "trials" && (rawKind !== null || rawStatus !== null)) {
      return { status: "invalid", message: "kind 和 status 只属于 Trial Archive。" };
    }
    if (task !== "trials" && task !== "batch" && task !== "web" && task !== "linux" && rawPage !== null) {
      return { status: "invalid", message: "page 只属于 Trial Archive 或 Batch Registry。" };
    }
    if (task === "trials" && (experimentId !== null || evaluationId !== null || trialId !== null)) {
      return { status: "invalid", message: "Trial Archive 不接受父任务或 trial 资源参数。" };
    }
    if (task === "batch" && (
      experimentId !== null
      || evaluationId !== null
      || trialId !== null
      || rawKind !== null
      || rawStatus !== null
    )) {
      return { status: "invalid", message: "Batch Registry 只接受 registry_id 和 page。" };
    }

    return {
      status: "resolved",
      route: {
        task,
        experimentId,
        evaluationId,
        trialId,
        registryId,
        archiveKind: kindResult?.data ?? null,
        archiveStatus: statusResult?.data ?? null,
        page: task === "trials" || task === "batch" || task === "web" || task === "linux"
          ? pageResult?.data ?? 1
          : null,
      },
    };
  } catch (error: unknown) {
    return {
      status: "invalid",
      message: error instanceof Error ? error.message : "Task Gallery 查询参数解析失败。",
    };
  }
}

export function createTaskGalleryHash(route: TaskGalleryRoute): string {
  if (route.task !== "survey" && route.experimentId !== null) {
    throw new Error("Only Survey Playground may serialize experiment state.");
  }
  if (
    route.task !== "chat"
    && route.task !== "web"
    && route.task !== "linux"
    && route.evaluationId !== null
  ) {
    throw new Error("Only Chat, Web, or Linux Evaluation may serialize evaluation state.");
  }
  if (route.task === "survey" && route.trialId !== null && route.experimentId === null) {
    throw new Error("A Survey trial route requires its parent experiment identifier.");
  }
  if ((route.task === "chat" || route.task === "web") && route.trialId !== null && route.evaluationId === null) {
    throw new Error("A Chat trial route requires its parent evaluation identifier.");
  }
  if (route.task !== "survey" && route.task !== "chat" && route.task !== "web" && route.task !== "linux" && route.trialId !== null) {
    throw new Error("Only Survey or Chat detail may serialize trial state.");
  }
  if (route.task !== "batch" && route.registryId !== null) {
    throw new Error("Only Batch Registry may serialize registry state.");
  }
  if (route.task !== "trials" && (route.archiveKind !== null || route.archiveStatus !== null)) {
    throw new Error("Only Trial Archive may serialize filters.");
  }
  if (route.task !== "trials" && route.task !== "batch" && route.task !== "web" && route.task !== "linux" && route.page !== null) {
    throw new Error("Only Trial Archive or Batch Registry may serialize pagination.");
  }

  if (route.task === null) return "#/tasks";
  const parameters = new URLSearchParams({ task: taskKindSchema.parse(route.task) });
  if (route.experimentId !== null) {
    parameters.set("experiment_id", identifierSchema.parse(route.experimentId));
  }
  if (route.evaluationId !== null) {
    parameters.set("evaluation_id", identifierSchema.parse(route.evaluationId));
  }
  if (route.trialId !== null) {
    parameters.set("trial_id", identifierSchema.parse(route.trialId));
  }
  if (route.task === "trials") {
    if (route.archiveKind !== null) {
      parameters.set("kind", archiveKindSchema.parse(route.archiveKind));
    }
    if (route.archiveStatus !== null) {
      parameters.set("status", archiveStatusSchema.parse(route.archiveStatus));
    }
    parameters.set("page", String(positivePageSchema.parse(route.page ?? 1)));
  }
  if (route.task === "batch") {
    parameters.set("page", String(positivePageSchema.parse(route.page ?? 1)));
    if (route.registryId !== null) {
      parameters.set("registry_id", identifierSchema.parse(route.registryId));
    }
  }
  if (route.task === "web") {
    parameters.set("page", String(positivePageSchema.parse(route.page ?? 1)));
  }
  if (route.task === "linux") {
    parameters.set("page", String(positivePageSchema.parse(route.page ?? 1)));
  }
  return `#/tasks?${parameters.toString()}`;
}

export function taskGalleryRootRoute(): TaskGalleryRoute {
  return {
    task: null,
    experimentId: null,
    evaluationId: null,
    trialId: null,
    registryId: null,
    archiveKind: null,
    archiveStatus: null,
    page: null,
  };
}
