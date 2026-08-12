import { describe, expect, it } from "vitest";

import {
  createScenarioDetailEndpoint,
  scenarioCreateRequestSchema,
  scenarioDetailSchema,
  scenarioSummarySchema,
  scenariosResponseSchema,
} from "./scenarioContracts";

const scenarioId = "16f59066-b4e9-4d71-8c51-7742f85943f2";
const worldModelId = "a4d8d10b-d7e5-4a34-b135-a6e6f1101834";
const worldSnapshotId = "33f6aee5-2912-4429-85ab-601dbfe41c19";
const baselineId = "4fe5517f-6dd4-4376-8337-d94f50acc074";
const alternativeId = "02e09ee8-88e8-4831-9427-f891255219ef";
const interventionId = "d70671a6-a681-49c0-aa03-194d38b82963";
const snapshotDigest = "a".repeat(64);
const scenarioDigest = "b".repeat(64);

const validSnapshot = {
  world_model_id: worldModelId,
  world_snapshot_id: worldSnapshotId,
  version: 2,
  snapshot_sha256: snapshotDigest,
  company_name: "星河科技有限公司",
  evidence_count: 3,
};

const validSummary = {
  id: scenarioId,
  title: "星河科技回应策略实验",
  decision_question: "主动公开进展是否比保持现状更能降低质疑？",
  created_at: "2026-08-12T08:30:00Z",
  scenario_sha256: scenarioDigest,
  snapshot: validSnapshot,
};

const validIntervention = {
  id: interventionId,
  position: 0,
  kind: "initial_post",
  actor: "snapshot_company",
  channel: "reddit",
  content: "我们将公开供应链进展并持续更新。",
  offset_minutes: 30,
};

const validDetail = {
  ...validSummary,
  baseline: {
    id: baselineId,
    position: 0,
    name: "保持当前状态",
    hypothesis: "若不发布新内容，现有讨论将沿当前趋势演化。",
    interventions: [],
  },
  alternatives: [
    {
      id: alternativeId,
      position: 1,
      name: "主动公开进展",
      hypothesis: "透明披露将减少信息空白带来的质疑。",
      interventions: [validIntervention],
    },
  ],
};

const validRequest = {
  title: "星河科技回应策略实验",
  decision_question: "主动公开进展是否比保持现状更能降低质疑？",
  world_model_id: worldModelId,
  world_snapshot_id: worldSnapshotId,
  baseline: {
    name: "保持当前状态",
    hypothesis: "若不发布新内容，现有讨论将沿当前趋势演化。",
  },
  alternatives: [
    {
      name: "主动公开进展",
      hypothesis: "透明披露将减少信息空白带来的质疑。",
      interventions: [
        {
          kind: "initial_post",
          actor: "snapshot_company",
          channel: "reddit",
          content: "我们将公开供应链进展并持续更新。",
          offset_minutes: 30,
        },
      ],
    },
  ],
};

describe("decision scenario contracts", () => {
  it("accepts the exact list, detail, and create shapes", () => {
    expect(scenarioSummarySchema.safeParse(validSummary).success).toBe(true);
    expect(scenariosResponseSchema.safeParse({ items: [validSummary], total: 1 }).success).toBe(true);
    expect(scenarioDetailSchema.safeParse(validDetail).success).toBe(true);
    expect(scenarioCreateRequestSchema.safeParse(validRequest).success).toBe(true);
  });

  it("keeps variants out of summaries and rejects undeclared fields", () => {
    expect(
      scenarioSummarySchema.safeParse({
        ...validSummary,
        alternatives: validDetail.alternatives,
      }).success,
    ).toBe(false);
    expect(
      scenarioCreateRequestSchema.safeParse({
        ...validRequest,
        acknowledged: true,
      }).success,
    ).toBe(false);
  });

  it("requires an empty baseline and fixed intervention semantics", () => {
    expect(
      scenarioDetailSchema.safeParse({
        ...validDetail,
        baseline: {
          ...validDetail.baseline,
          interventions: [validIntervention],
        },
      }).success,
    ).toBe(false);
    expect(
      scenarioCreateRequestSchema.safeParse({
        ...validRequest,
        alternatives: [
          {
            ...validRequest.alternatives[0],
            interventions: [
              {
                ...validRequest.alternatives[0]?.interventions[0],
                channel: "twitter",
              },
            ],
          },
        ],
      }).success,
    ).toBe(false);
    expect(
      scenarioDetailSchema.safeParse({
        ...validDetail,
        alternatives: [
          {
            ...validDetail.alternatives[0],
            interventions: [{ ...validIntervention, actor: "operator" }],
          },
        ],
      }).success,
    ).toBe(false);
  });

  it("enforces text and scheduling limits in requests and responses", () => {
    expect(
      scenarioCreateRequestSchema.safeParse({
        ...validRequest,
        alternatives: [
          {
            ...validRequest.alternatives[0],
            name: "方".repeat(201),
          },
        ],
      }).success,
    ).toBe(false);
    expect(
      scenarioCreateRequestSchema.safeParse({
        ...validRequest,
        alternatives: [
          {
            ...validRequest.alternatives[0],
            hypothesis: "假".repeat(2_001),
          },
        ],
      }).success,
    ).toBe(false);
    expect(
      scenarioCreateRequestSchema.safeParse({
        ...validRequest,
        alternatives: [
          {
            ...validRequest.alternatives[0],
            interventions: [
              {
                ...validRequest.alternatives[0]?.interventions[0],
                content: "帖".repeat(4_001),
                offset_minutes: 1_441,
              },
            ],
          },
        ],
      }).success,
    ).toBe(false);
    expect(
      scenarioSummarySchema.safeParse({
        ...validSummary,
        snapshot: { ...validSnapshot, company_name: "企".repeat(301) },
      }).success,
    ).toBe(false);
    expect(
      scenarioSummarySchema.safeParse({
        ...validSummary,
        snapshot: { ...validSnapshot, company_name: "星河科技\n旧名称" },
      }).success,
    ).toBe(false);
    expect(
      scenarioDetailSchema.safeParse({
        ...validDetail,
        alternatives: [
          {
            ...validDetail.alternatives[0],
            hypothesis: "假".repeat(2_001),
            interventions: [
              {
                ...validIntervention,
                content: "帖".repeat(4_001),
                offset_minutes: 1_441,
              },
            ],
          },
        ],
      }).success,
    ).toBe(false);
  });

  it("enforces 1..5 alternatives and 1..20 posts per alternative", () => {
    expect(
      scenarioCreateRequestSchema.safeParse({
        ...validRequest,
        alternatives: [],
      }).success,
    ).toBe(false);

    const oversizedAlternatives = Array.from({ length: 6 }, () =>
      validRequest.alternatives[0],
    );
    const oversizedInterventions = Array.from({ length: 21 }, () =>
      validRequest.alternatives[0]?.interventions[0],
    );

    expect(
      scenarioCreateRequestSchema.safeParse({
        ...validRequest,
        alternatives: oversizedAlternatives,
      }).success,
    ).toBe(false);
    expect(
      scenarioCreateRequestSchema.safeParse({
        ...validRequest,
        alternatives: [
          {
            ...validRequest.alternatives[0],
            interventions: oversizedInterventions,
          },
        ],
      }).success,
    ).toBe(false);
  });

  it("requires sequential response positions and globally unique identifiers", () => {
    const secondIntervention = {
      ...validIntervention,
      id: "495d98f8-06eb-476d-966c-cb51efc7c770",
      position: 2,
    };

    expect(
      scenarioDetailSchema.safeParse({
        ...validDetail,
        alternatives: [
          {
            ...validDetail.alternatives[0],
            interventions: [validIntervention, secondIntervention],
          },
        ],
      }).success,
    ).toBe(false);
    expect(
      scenarioDetailSchema.safeParse({
        ...validDetail,
        alternatives: [
          validDetail.alternatives[0],
          {
            ...validDetail.alternatives[0],
            id: "a27d8829-3cfb-4128-8791-cf4525e66741",
            position: 3,
            interventions: [
              {
                ...validIntervention,
                id: "a35536e9-4258-4570-943e-7e2977ed65a7",
              },
            ],
          },
        ],
      }).success,
    ).toBe(false);
  });

  it("encodes detail identifiers", () => {
    expect(createScenarioDetailEndpoint("scenario/中国")).toBe(
      "/api/v2/scenarios/scenario%2F%E4%B8%AD%E5%9B%BD",
    );
  });
});
