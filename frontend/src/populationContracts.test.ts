import { describe, expect, it } from "vitest";

import {
  cohortCreateRequestSchema,
  cohortDetailSchema,
  cohortSummarySchema,
  cohortsResponseSchema,
  createCohortDetailEndpoint,
  createPopulationPersonasEndpoint,
  personaSummarySchema,
  populationDatasetsResponseSchema,
  populationDatasetSummarySchema,
  populationPersonasResponseSchema,
} from "./populationContracts";

const datasetId = "16f59066-b4e9-4d71-8c51-7742f85943f2";
const personaId = "02e09ee8-88e8-4831-9427-f891255219ef";
const secondPersonaId = "33f6aee5-2912-4429-85ab-601dbfe41c19";
const cohortId = "6f22ff11-76ae-4a32-bc4b-7acd80efe19a";
const datasetDigest = "a".repeat(64);
const manifestDigest = "b".repeat(64);
const profileDigest = "c".repeat(64);
const secondProfileDigest = "d".repeat(64);
const cohortDigest = "e".repeat(64);

const validDataset = {
  id: datasetId,
  slug: "matraix-zh-v1",
  display_name: "MatrAIx 中文 Persona v1",
  schema_version: "matraix.persona/v1",
  parent_pool: "MatrAIx/public-personas",
  source_repository: "https://github.com/example/matraix-personas",
  persona_count: 2,
  manifest_sha256: manifestDigest,
  dataset_sha256: datasetDigest,
  created_at: "2026-08-12T08:30:00Z",
};

const validPersona = {
  id: personaId,
  dataset_id: datasetId,
  persona_id: "persona.cn.0001",
  display_name: "陈晓雯",
  source: "matraix.public",
  profile_sha256: profileDigest,
  attributes: [
    { name: "age_band", value: "30-39" },
    { name: "region", value: "华东" },
  ],
};

const validSecondPersona = {
  ...validPersona,
  id: secondPersonaId,
  persona_id: "persona.cn.0002",
  display_name: "赵启明",
  profile_sha256: secondProfileDigest,
};

const validSummary = {
  id: cohortId,
  title: "华东供应链观察组",
  dataset: {
    id: datasetId,
    slug: validDataset.slug,
    dataset_sha256: datasetDigest,
  },
  persona_count: 2,
  cohort_sha256: cohortDigest,
  created_at: "2026-08-12T09:00:00Z",
};

const validDetail = {
  ...validSummary,
  members: [
    { position: 0, persona: validPersona },
    { position: 1, persona: validSecondPersona },
  ],
};

describe("population contracts", () => {
  it("accepts the exact dataset, persona, cohort, and directory shapes", () => {
    expect(populationDatasetSummarySchema.safeParse(validDataset).success).toBe(true);
    expect(
      populationDatasetsResponseSchema.safeParse({ items: [validDataset], total: 1 }).success,
    ).toBe(true);
    expect(personaSummarySchema.safeParse(validPersona).success).toBe(true);
    expect(
      populationPersonasResponseSchema.safeParse({
        items: [validPersona, validSecondPersona],
        page: 1,
        page_size: 20,
        total: 2,
      }).success,
    ).toBe(true);
    expect(cohortSummarySchema.safeParse(validSummary).success).toBe(true);
    expect(cohortDetailSchema.safeParse(validDetail).success).toBe(true);
    expect(cohortsResponseSchema.safeParse({ items: [validSummary], total: 1 }).success).toBe(true);
  });

  it("rejects undeclared fields at every external response boundary", () => {
    expect(
      populationDatasetSummarySchema.safeParse({ ...validDataset, mutable: true }).success,
    ).toBe(false);
    expect(
      personaSummarySchema.safeParse({ ...validPersona, biography: "undeclared" }).success,
    ).toBe(false);
    expect(
      cohortDetailSchema.safeParse({ ...validDetail, semantic_run_ready: true }).success,
    ).toBe(false);
  });

  it("enforces exact backend string, count, and digest bounds", () => {
    expect(
      populationDatasetSummarySchema.safeParse({
        ...validDataset,
        slug: "matraix.zh-personas:v1",
      }).success,
    ).toBe(true);
    expect(
      populationDatasetSummarySchema.safeParse({
        ...validDataset,
        slug: "matraix/zh personas-v1",
      }).success,
    ).toBe(false);
    expect(
      populationDatasetSummarySchema.safeParse({
        ...validDataset,
        schema_version: "v".repeat(33),
      }).success,
    ).toBe(false);
    expect(
      populationDatasetSummarySchema.safeParse({ ...validDataset, persona_count: 0 }).success,
    ).toBe(false);
    expect(
      populationDatasetSummarySchema.safeParse({
        ...validDataset,
        persona_count: 1_000_001,
      }).success,
    ).toBe(false);
    expect(
      populationDatasetSummarySchema.safeParse({
        ...validDataset,
        source_repository: "r".repeat(501),
      }).success,
    ).toBe(false);
    expect(
      personaSummarySchema.safeParse({
        ...validPersona,
        source: "source/with/slash",
      }).success,
    ).toBe(false);
    expect(
      personaSummarySchema.safeParse({ ...validPersona, profile_sha256: "not-a-hash" }).success,
    ).toBe(false);
    expect(
      personaSummarySchema.safeParse({
        ...validPersona,
        persona_id: `p${"x".repeat(128)}`,
      }).success,
    ).toBe(false);
  });

  it("requires unique Persona attributes sorted by name", () => {
    expect(
      personaSummarySchema.safeParse({
        ...validPersona,
        attributes: [...validPersona.attributes].reverse(),
      }).success,
    ).toBe(false);
    expect(
      personaSummarySchema.safeParse({
        ...validPersona,
        attributes: [validPersona.attributes[0], validPersona.attributes[0]],
      }).success,
    ).toBe(false);
    expect(
      personaSummarySchema.safeParse({
        ...validPersona,
        attributes: [{ name: "region", value: "x".repeat(501) }],
      }).success,
    ).toBe(false);
  });

  it("requires 1 to 100 ordered unique UUID Persona selections", () => {
    const validRequest = {
      title: validSummary.title,
      dataset_id: datasetId,
      persona_ids: [personaId, secondPersonaId],
    };

    expect(cohortCreateRequestSchema.safeParse(validRequest).success).toBe(true);
    expect(
      cohortCreateRequestSchema.safeParse({ ...validRequest, persona_ids: [] }).success,
    ).toBe(false);
    expect(
      cohortCreateRequestSchema.safeParse({
        ...validRequest,
        persona_ids: [personaId, personaId],
      }).success,
    ).toBe(false);
    expect(
      cohortCreateRequestSchema.safeParse({ ...validRequest, dataset_id: "not-a-uuid" }).success,
    ).toBe(false);
    expect(
      cohortCreateRequestSchema.safeParse({
        ...validRequest,
        persona_ids: Array.from(
          { length: 101 },
          (_, index) => `00000000-0000-4000-8000-${index.toString(16).padStart(12, "0")}`,
        ),
      }).success,
    ).toBe(false);
  });

  it("requires contiguous cohort positions, unique members, and one dataset", () => {
    expect(
      cohortDetailSchema.safeParse({
        ...validDetail,
        members: [validDetail.members[0], { ...validDetail.members[1], position: 2 }],
      }).success,
    ).toBe(false);
    expect(
      cohortDetailSchema.safeParse({
        ...validDetail,
        persona_count: 1,
        members: [{ ...validDetail.members[0], position: 100 }],
      }).success,
    ).toBe(false);
    expect(
      cohortDetailSchema.safeParse({
        ...validDetail,
        members: [validDetail.members[0], { position: 1, persona: validPersona }],
      }).success,
    ).toBe(false);
    expect(
      cohortDetailSchema.safeParse({
        ...validDetail,
        members: [
          validDetail.members[0],
          {
            position: 1,
            persona: {
              ...validSecondPersona,
              dataset_id: "a021647c-c8f1-4b71-94d1-057a6de8da61",
            },
          },
        ],
      }).success,
    ).toBe(false);
  });

  it("builds encoded query and detail endpoints without implicit defaults", () => {
    expect(
      createPopulationPersonasEndpoint(datasetId, {
        q: "华东 供应链",
        page: 2,
        pageSize: 10,
      }),
    ).toBe(
      `/api/v2/populations/datasets/${datasetId}/personas?page=2&page_size=10&q=%E5%8D%8E%E4%B8%9C+%E4%BE%9B%E5%BA%94%E9%93%BE`,
    );
    expect(
      createPopulationPersonasEndpoint(datasetId, { q: null, page: 1, pageSize: 20 }),
    ).toBe(`/api/v2/populations/datasets/${datasetId}/personas?page=1&page_size=20`);
    expect(createCohortDetailEndpoint(cohortId)).toBe(
      `/api/v2/populations/cohorts/${cohortId}`,
    );
    expect(() =>
      createPopulationPersonasEndpoint(datasetId, { q: "x", page: 1, pageSize: 20 }),
    ).toThrow();
  });
});
