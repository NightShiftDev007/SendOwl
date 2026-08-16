import { describe, expect, it } from "vitest";

import { createTaskGalleryHash, resolveTaskGalleryRoute } from "./taskGalleryRoute";

const evaluationId = "2ce907de-4709-4eb6-b702-abac631607c7";
const trialId = "ff51bd82-385d-48ad-aa3c-9277dd927380";

describe("Task Gallery route", () => {
  it("preserves an explicit Chat evaluation and trial selection", () => {
    const hash = createTaskGalleryHash({
      task: "chat",
      experimentId: null,
      evaluationId,
      trialId,
      registryId: null,
      archiveKind: null,
      archiveStatus: null,
      page: 1,
    });
    expect(resolveTaskGalleryRoute(hash.slice("#/tasks?".length))).toEqual({
      status: "resolved",
      route: {
        task: "chat",
        experimentId: null,
        evaluationId,
        trialId,
        registryId: null,
        archiveKind: null,
        archiveStatus: null,
        page: 1,
      },
    });
  });

  it("preserves an explicit Survey experiment and trial selection", () => {
    const hash = createTaskGalleryHash({
      task: "survey",
      experimentId: evaluationId,
      evaluationId: null,
      trialId,
      registryId: null,
      archiveKind: null,
      archiveStatus: null,
      page: 1,
    });
    expect(hash).toBe(
      `#/tasks?task=survey&experiment_id=${evaluationId}&trial_id=${trialId}&page=1`,
    );
    expect(resolveTaskGalleryRoute(hash.slice("#/tasks?".length))).toMatchObject({
      status: "resolved",
      route: { task: "survey", experimentId: evaluationId, trialId },
    });
  });

  it("preserves an explicit Web evaluation, trial, and page", () => {
    const hash = createTaskGalleryHash({
      task: "web",
      experimentId: null,
      evaluationId,
      trialId,
      registryId: null,
      archiveKind: null,
      archiveStatus: null,
      page: 2,
    });
    expect(hash).toBe(
      `#/tasks?task=web&evaluation_id=${evaluationId}&trial_id=${trialId}&page=2`,
    );
    expect(resolveTaskGalleryRoute(hash.slice("#/tasks?".length))).toMatchObject({
      status: "resolved",
      route: { task: "web", evaluationId, trialId, page: 2 },
    });
  });

  it("preserves an explicit Linux evaluation parent", () => {
    const hash = createTaskGalleryHash({
      task: "linux",
      experimentId: null,
      evaluationId,
      trialId: null,
      registryId: null,
      archiveKind: null,
      archiveStatus: null,
      page: 2,
    });
    expect(hash).toBe(`#/tasks?task=linux&evaluation_id=${evaluationId}&page=2`);
    expect(resolveTaskGalleryRoute(hash.slice("#/tasks?".length))).toMatchObject({
      status: "resolved",
      route: { task: "linux", evaluationId, page: 2 },
    });
  });

  it("normalizes Trial Archive to explicit first-page state", () => {
    expect(resolveTaskGalleryRoute("task=trials&kind=chat&status=failed")).toEqual({
      status: "resolved",
      route: {
        task: "trials",
        experimentId: null,
        evaluationId: null,
        trialId: null,
        registryId: null,
        archiveKind: "chat",
        archiveStatus: "failed",
        page: 1,
      },
    });
  });

  it("serializes explicit Trial Archive pagination", () => {
    expect(createTaskGalleryHash({
      task: "trials",
      experimentId: null,
      evaluationId: null,
      trialId: null,
      registryId: null,
      archiveKind: "survey",
      archiveStatus: "succeeded",
      page: 3,
    })).toBe("#/tasks?task=trials&kind=survey&status=succeeded&page=3");
  });

  it("normalizes and serializes an explicit Batch Registry selection", () => {
    expect(resolveTaskGalleryRoute(`task=batch&registry_id=${evaluationId}`)).toEqual({
      status: "resolved",
      route: {
        task: "batch",
        experimentId: null,
        evaluationId: null,
        trialId: null,
        registryId: evaluationId,
        archiveKind: null,
        archiveStatus: null,
        page: 1,
      },
    });
    expect(createTaskGalleryHash({
      task: "batch",
      experimentId: null,
      evaluationId: null,
      trialId: null,
      registryId: evaluationId,
      archiveKind: null,
      archiveStatus: null,
      page: 3,
    })).toBe(`#/tasks?task=batch&page=3&registry_id=${evaluationId}`);
  });

  it.each([
    "task=chat&unknown=true",
    "task=chat&task=chat",
    "task=chat&evaluation_id=broken",
    `task=survey&evaluation_id=${evaluationId}`,
    `task=chat&trial_id=${trialId}`,
    `task=survey&trial_id=${trialId}`,
    "task=trials&page=0",
    "task=trials&page=1&page=2",
    "task=trials&kind=os_app",
    "task=trials&status=unknown",
    `task=trials&experiment_id=${evaluationId}`,
    "task=batch&page=0",
    "task=batch&page=1&page=2",
    `task=batch&registry_id=${evaluationId}&registry_id=${evaluationId}`,
    "task=batch&registry_id=broken",
    "task=batch&kind=survey",
    `task=trials&registry_id=${evaluationId}`,
  ])("rejects invalid state: %s", (query) => {
    expect(resolveTaskGalleryRoute(query).status).toBe("invalid");
  });
});
