import { describe, expect, it } from "vitest";

import {
  evaluateTaskAvailability,
  type RuntimeReadinessByKind,
} from "./taskRuntimeReadiness";

const readyProbes: RuntimeReadinessByKind = {
  platform: { status: "ready" },
  semantic: { status: "ready" },
  survey: { status: "ready" },
  chat: { status: "ready" },
  web: { status: "ready" },
  linux: { status: "ready" },
  archive: { status: "ready" },
};

describe("Task Gallery runtime readiness", () => {
  it("never promotes a missing or contract-only capability to runnable", () => {
    expect(
      evaluateTaskAvailability(
        { expectedState: "runtime_ready", readinessKind: "platform" },
        null,
        readyProbes,
      ).availability,
    ).toBe("missing");
    expect(
      evaluateTaskAvailability(
        { expectedState: "runtime_ready", readinessKind: "platform" },
        "contract_ready",
        readyProbes,
      ).availability,
    ).toBe("contract");
  });

  it("keeps intentionally contract-only directory items non-runnable", () => {
    expect(
      evaluateTaskAvailability(
        { expectedState: "contract_ready", readinessKind: null },
        "runtime_ready",
        readyProbes,
      ).availability,
    ).toBe("contract");
  });

  it("keeps historical read-only capabilities out of new-work launch paths", () => {
    const decision = evaluateTaskAvailability(
      { expectedState: "runtime_ready", readinessKind: "platform" },
      "legacy_readonly",
      readyProbes,
    );

    expect(decision.availability).toBe("contract");
    expect(decision.reason).toContain("历史读取");
  });

  it("shows verification while a required readiness endpoint is loading", () => {
    const decision = evaluateTaskAvailability(
      { expectedState: "runtime_ready", readinessKind: "semantic" },
      "runtime_ready",
      { ...readyProbes, semantic: { status: "loading" } },
    );

    expect(decision.availability).toBe("verifying");
    expect(decision.reason).toContain("正在核验");
  });

  it("blocks the launch entry and retains the safe unready reason", () => {
    const decision = evaluateTaskAvailability(
      { expectedState: "runtime_ready", readinessKind: "survey" },
      "runtime_ready",
      {
        ...readyProbes,
        survey: {
          status: "unready",
          reason: "在线 Survey worker 未暴露完整模型配置。",
        },
      },
    );

    expect(decision).toEqual({
      availability: "unready",
      reason: "在线 Survey worker 未暴露完整模型配置。",
    });
  });

  it("treats readiness request errors as an explicit runtime block", () => {
    const decision = evaluateTaskAvailability(
      { expectedState: "runtime_ready", readinessKind: "platform" },
      "runtime_ready",
      {
        ...readyProbes,
        platform: {
          status: "error",
          reason: "无法完成 OASIS platform readiness 核验：HTTP 503",
        },
      },
    );

    expect(decision).toEqual({
      availability: "unready",
      reason: "无法完成 OASIS platform readiness 核验：HTTP 503",
    });
  });

  it("allows launch only after both static capability and required probe are ready", () => {
    expect(
      evaluateTaskAvailability(
        { expectedState: "runtime_ready", readinessKind: "platform" },
        "runtime_ready",
        readyProbes,
      ).availability,
    ).toBe("runtime");
  });

  it("requires the dedicated Chat readiness probe before opening Chatbot Evaluation", () => {
    expect(
      evaluateTaskAvailability(
        { expectedState: "runtime_ready", readinessKind: "chat" },
        "runtime_ready",
        { ...readyProbes, chat: { status: "loading" } },
      ).availability,
    ).toBe("verifying");

    expect(
      evaluateTaskAvailability(
        { expectedState: "runtime_ready", readinessKind: "chat" },
        "runtime_ready",
        readyProbes,
      ).availability,
    ).toBe("runtime");
  });

  it("allows the read-only archive from its runtime capability without LLM readiness", () => {
    expect(
      evaluateTaskAvailability(
        { expectedState: "runtime_ready", readinessKind: "archive" },
        "runtime_ready",
        readyProbes,
      ).availability,
    ).toBe("runtime");
  });

  it("blocks runtime capabilities that do not have a readiness probe", () => {
    const decision = evaluateTaskAvailability(
      { expectedState: "runtime_ready", readinessKind: null },
      "runtime_ready",
      readyProbes,
    );

    expect(decision.availability).toBe("unready");
    expect(decision.reason).toContain("没有该任务的实时 readiness");
  });
});
