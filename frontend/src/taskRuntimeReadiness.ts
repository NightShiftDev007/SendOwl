import type { CapabilityDescriptor } from "./systemCapabilities";

export type TaskRuntimeKind = "platform" | "semantic" | "survey" | "chat" | "web" | "linux" | "archive";
export type TaskAvailability =
  | "runtime"
  | "verifying"
  | "unready"
  | "contract"
  | "missing";

export type RuntimeReadinessProbe =
  | { readonly status: "loading" }
  | { readonly status: "ready" }
  | { readonly status: "unready"; readonly reason: string }
  | { readonly status: "error"; readonly reason: string };

export type RuntimeReadinessByKind = Readonly<
  Record<TaskRuntimeKind, RuntimeReadinessProbe>
>;

export interface TaskRuntimeRequirement {
  readonly expectedState: CapabilityDescriptor["state"];
  readonly readinessKind: TaskRuntimeKind | null;
}

export interface TaskAvailabilityDecision {
  readonly availability: TaskAvailability;
  readonly reason: string;
}

export function evaluateTaskAvailability(
  requirement: TaskRuntimeRequirement,
  capabilityState: CapabilityDescriptor["state"] | null,
  readiness: RuntimeReadinessByKind,
): TaskAvailabilityDecision {
  if (capabilityState === null) {
    return {
      availability: "missing",
      reason: "当前后端没有该 capability。",
    };
  }

  if (requirement.expectedState === "contract_ready") {
    return {
      availability: "contract",
      reason: "该目录项只声明评测契约，尚未提供可执行入口。",
    };
  }

  if (capabilityState !== "runtime_ready") {
    return {
      availability: "contract",
      reason: "Capability 当前仅为 contract_ready，执行器尚未接通。",
    };
  }

  if (requirement.readinessKind === null) {
    return {
      availability: "unready",
      reason: "当前目录没有该任务的实时 readiness 核验链路；为避免误启动，入口保持关闭。",
    };
  }

  const probe = readiness[requirement.readinessKind];

  if (probe.status === "loading") {
    return {
      availability: "verifying",
      reason: "正在核验实际 worker 与运行时配置。",
    };
  }

  if (probe.status === "ready") {
    return {
      availability: "runtime",
      reason: "静态 capability 与实时 readiness 均已通过核验。",
    };
  }

  return {
    availability: "unready",
    reason: probe.reason,
  };
}
