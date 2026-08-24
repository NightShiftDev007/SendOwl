import { describe, expect, it } from "vitest";

import { resolveSectionFromHash } from "./App";
import { requireNavigationItem } from "./domain";

describe("hash route resolution", () => {
  it.each(["", "#", "#/overview", "#/projects", "#/threads", "#/media", "#/policy", "#/world", "#/decisions", "#/personas", "#/tasks", "#/runs", "#/reports"])(
    "resolves the legal route %s",
    (hash) => {
      expect(resolveSectionFromHash(hash).status).toBe("resolved");
    },
  );

  it("resolves a strict semantic Run Studio deep link", () => {
    expect(resolveSectionFromHash(
      "#/runs?mode=semantic&experiment_id=2ce907de-4709-4eb6-b702-abac631607c7",
    )).toMatchObject({
      status: "resolved",
      section: "runs",
      runStudioRoute: {
        mode: "semantic",
        experimentId: "2ce907de-4709-4eb6-b702-abac631607c7",
      },
    });
  });

  it("routes the default Run Studio and Project / Run deep links to the native workspace", () => {
    expect(resolveSectionFromHash("#/runs")).toMatchObject({
      status: "resolved",
      section: "runs",
      runStudioRoute: { mode: "native", projectId: null, runId: null },
    });
    expect(resolveSectionFromHash(
      "#/runs?project_id=748de69e-3192-496d-9b2c-6ca72ac85575&run_id=32f4e1ed-985e-4786-b965-4e37436bda9f",
    )).toMatchObject({
      status: "resolved",
      section: "runs",
      runStudioRoute: {
        mode: "native",
        projectId: "748de69e-3192-496d-9b2c-6ca72ac85575",
        runId: "32f4e1ed-985e-4786-b965-4e37436bda9f",
      },
    });
  });

  it("preserves a Persona World Cohort handoff", () => {
    expect(resolveSectionFromHash(
      "#/runs?mode=semantic&cohort_id=ff51bd82-385d-48ad-aa3c-9277dd927380",
    )).toMatchObject({
      status: "resolved",
      section: "runs",
      runStudioRoute: {
        mode: "semantic",
        cohortId: "ff51bd82-385d-48ad-aa3c-9277dd927380",
      },
    });
  });

  it("preserves a Decision Workspace Scenario handoff", () => {
    expect(resolveSectionFromHash(
      "#/runs?mode=semantic&scenario_id=af9b38d8-f040-4284-a1f5-b3e7ecf18066",
    )).toMatchObject({
      status: "resolved",
      section: "runs",
      runStudioRoute: {
        mode: "semantic",
        scenarioId: "af9b38d8-f040-4284-a1f5-b3e7ecf18066",
      },
    });
  });

  it("preserves a strict media Topic Observatory deep link", () => {
    expect(resolveSectionFromHash(
      "#/media?topic_id=693f538f-527c-428a-8dfe-97c3b0ad2907&lens=topic&country=CN",
    )).toMatchObject({
      status: "resolved",
      section: "media",
      mediaRoute: {
        topicId: "693f538f-527c-428a-8dfe-97c3b0ad2907",
        sourceId: null,
        lens: "topic",
        country: "CN",
      },
    });
  });

  it("preserves the media source health lens", () => {
    expect(resolveSectionFromHash("#/media?lens=sources")).toMatchObject({
      status: "resolved",
      section: "media",
      mediaRoute: {
        topicId: null,
        sourceId: null,
        lens: "sources",
        country: null,
      },
    });
  });

  it("preserves a strict WorldModel snapshot deep link", () => {
    expect(resolveSectionFromHash(
      "#/world?world_model_id=2ce907de-4709-4eb6-b702-abac631607c7&snapshot_id=ff51bd82-385d-48ad-aa3c-9277dd927380",
    )).toMatchObject({
      status: "resolved",
      section: "world",
      worldRoute: {
        worldModelId: "2ce907de-4709-4eb6-b702-abac631607c7",
        snapshotId: "ff51bd82-385d-48ad-aa3c-9277dd927380",
      },
    });
  });

  it("preserves an explicit Media evidence handoff to World", () => {
    expect(resolveSectionFromHash(
      "#/world?evidence_id=ff51bd82-385d-48ad-aa3c-9277dd927380",
    )).toMatchObject({
      status: "resolved",
      section: "world",
      worldRoute: {
        worldModelId: null,
        snapshotId: null,
        evidenceId: "ff51bd82-385d-48ad-aa3c-9277dd927380",
      },
    });
  });

  it("preserves an exact frozen WorldSnapshot handoff to Research Projects", () => {
    expect(resolveSectionFromHash(
      "#/projects?world_model_id=2ce907de-4709-4eb6-b702-abac631607c7&snapshot_id=ff51bd82-385d-48ad-aa3c-9277dd927380",
    )).toMatchObject({
      status: "resolved",
      section: "projects",
      researchProjectRoute: {
        worldModelId: "2ce907de-4709-4eb6-b702-abac631607c7",
        snapshotId: "ff51bd82-385d-48ad-aa3c-9277dd927380",
      },
    });
  });

  it("resolves persistent decision and report resource deep links", () => {
    const identity = "2ce907de-4709-4eb6-b702-abac631607c7";
    expect(resolveSectionFromHash(`#/threads?thread_id=${identity}`)).toMatchObject({
      status: "resolved",
      section: "threads",
      resourceId: identity,
    });
    expect(resolveSectionFromHash(`#/reports?experiment_id=${identity}`)).toMatchObject({
      status: "resolved",
      section: "reports",
      reportWorkspaceRoute: {
        mode: "legacy",
        experimentId: identity,
      },
    });
  });

  it("resolves native single-run report deep links and the explicit legacy archive", () => {
    const projectId = "2ce907de-4709-4eb6-b702-abac631607c7";
    const runId = "ff51bd82-385d-48ad-aa3c-9277dd927380";
    expect(resolveSectionFromHash(
      `#/reports?project_id=${projectId}&run_id=${runId}`,
    )).toMatchObject({
      status: "resolved",
      section: "reports",
      reportWorkspaceRoute: { mode: "native", projectId, runId },
    });
    expect(resolveSectionFromHash("#/reports?legacy=1")).toMatchObject({
      status: "resolved",
      section: "reports",
      reportWorkspaceRoute: { mode: "legacy", experimentId: null },
    });
  });

  it("resolves the Survey Playground inside Task Gallery", () => {
    expect(resolveSectionFromHash("#/tasks?task=survey")).toMatchObject({
      status: "resolved",
      section: "tasks",
      taskGalleryRoute: {
        task: "survey",
        experimentId: null,
        evaluationId: null,
        trialId: null,
        archiveKind: null,
        archiveStatus: null,
        page: 1,
      },
    });
  });

  it("preserves a strict Chat Evaluation and Persona trial deep link", () => {
    expect(resolveSectionFromHash(
      "#/tasks?task=chat&evaluation_id=2ce907de-4709-4eb6-b702-abac631607c7&trial_id=ff51bd82-385d-48ad-aa3c-9277dd927380",
    )).toMatchObject({
      status: "resolved",
      section: "tasks",
      taskGalleryRoute: {
        task: "chat",
        experimentId: null,
        evaluationId: "2ce907de-4709-4eb6-b702-abac631607c7",
        trialId: "ff51bd82-385d-48ad-aa3c-9277dd927380",
        archiveKind: null,
        archiveStatus: null,
        page: 1,
      },
    });
  });

  it("preserves Trial Archive filters and explicit pagination", () => {
    expect(resolveSectionFromHash(
      "#/tasks?task=trials&kind=survey&status=succeeded&page=2",
    )).toMatchObject({
      status: "resolved",
      section: "tasks",
      taskGalleryRoute: {
        task: "trials",
        archiveKind: "survey",
        archiveStatus: "succeeded",
        page: 2,
      },
    });
  });

  it("preserves a strict Batch Registry deep link", () => {
    expect(resolveSectionFromHash(
      "#/tasks?task=batch&page=2&registry_id=2ce907de-4709-4eb6-b702-abac631607c7",
    )).toMatchObject({
      status: "resolved",
      section: "tasks",
      taskGalleryRoute: {
        task: "batch",
        registryId: "2ce907de-4709-4eb6-b702-abac631607c7",
        page: 2,
      },
    });
  });

  it.each([
    "#/runs?unknown=true",
    "#/runs?mode=semantic&experiment_id=broken",
    "#/media?mode=semantic",
    "#/media?topic_id=broken&lens=topic",
    "#/media?lens=topic&country=cn",
    "#/world?snapshot_id=ff51bd82-385d-48ad-aa3c-9277dd927380",
    "#/world?world_model_id=broken",
    "#/world?world_model_id=2ce907de-4709-4eb6-b702-abac631607c7&unknown=true",
    "#/projects?world_model_id=2ce907de-4709-4eb6-b702-abac631607c7",
    "#/projects?snapshot_id=ff51bd82-385d-48ad-aa3c-9277dd927380",
    "#/projects?world_model_id=broken&snapshot_id=broken",
    "#/projects?unknown=true",
    "#/threads?thread_id=broken",
    "#/reports?unknown=true",
    "#/reports?project_id=2ce907de-4709-4eb6-b702-abac631607c7",
    "#/reports?legacy=0",
    "#/reports?legacy=1&project_id=2ce907de-4709-4eb6-b702-abac631607c7&run_id=ff51bd82-385d-48ad-aa3c-9277dd927380",
    "#/tasks?task=harbor",
    "#/tasks?unknown=survey",
    "#/tasks?task=survey&task=survey",
    "#/tasks?task=chat&evaluation_id=broken",
    "#/tasks?task=chat&trial_id=ff51bd82-385d-48ad-aa3c-9277dd927380",
    "#/tasks?task=survey&evaluation_id=2ce907de-4709-4eb6-b702-abac631607c7",
  ])("rejects the invalid deep link %s", (hash) => {
    expect(resolveSectionFromHash(hash).status).toBe("invalid");
  });

  it("rejects the removed company workspace route", () => {
    expect(resolveSectionFromHash("#/companies").status).toBe("invalid");
  });

  it("returns a diagnosable error for a malformed hash instead of throwing", () => {
    expect(resolveSectionFromHash("#media")).toMatchObject({
      status: "invalid",
      hash: "#media",
    });
  });

  it("returns a diagnosable error for an unknown workspace", () => {
    expect(resolveSectionFromHash("#/not-a-workspace")).toMatchObject({
      status: "invalid",
      hash: "#/not-a-workspace",
    });
  });

  it("exposes the world model route as a runtime workspace", () => {
    expect(requireNavigationItem("world").state).toBe("available");
  });

  it("exposes Policy evidence as a runtime workspace", () => {
    expect(requireNavigationItem("policy").state).toBe("available");
  });

  it("exposes persistent decision tasks as a runtime workspace", () => {
    expect(requireNavigationItem("threads").state).toBe("available");
  });

  it("exposes the decision experiment route as a runtime workspace", () => {
    expect(requireNavigationItem("decisions").state).toBe("available");
  });

  it("exposes the OASIS platform-smoke route as a runtime workspace", () => {
    expect(requireNavigationItem("runs").state).toBe("available");
  });

  it("exposes Persona World as a runtime workspace", () => {
    expect(requireNavigationItem("personas").state).toBe("available");
  });

  it("exposes Task Gallery as a runtime workspace", () => {
    expect(requireNavigationItem("tasks").state).toBe("available");
  });

  it("exposes decision reports as a runtime workspace", () => {
    expect(requireNavigationItem("reports").state).toBe("available");
  });
});
