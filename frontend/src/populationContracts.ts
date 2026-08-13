import { z } from "zod";

import { getJson, postJson } from "./apiClient";
import { sha256DigestSchema } from "./mediaContracts";

const populationsEndpoint = "/api/v2/populations";
const datasetsEndpoint = `${populationsEndpoint}/datasets`;
const cohortsEndpoint = `${populationsEndpoint}/cohorts`;
const identifierSchema = z.string().uuid();
const isoTimestampSchema = z.string().datetime({ offset: true });
const nonEmptyTextSchema = z.string().trim().min(1);
const singleLineTextSchema = nonEmptyTextSchema.regex(
  /^[^\r\n]+$/u,
  "Expected a single line of text",
);
const identifierTextSchema = z
  .string()
  .trim()
  .min(1)
  .max(128)
  .regex(/^[A-Za-z0-9][A-Za-z0-9_.:-]*$/u);
const datasetSlugSchema = identifierTextSchema;
const datasetReferenceSchema = nonEmptyTextSchema.max(500).nullable();
const cohortTitleSchema = singleLineTextSchema.max(200);

export const populationDatasetSummarySchema = z
  .object({
    id: identifierSchema,
    slug: datasetSlugSchema,
    display_name: nonEmptyTextSchema.max(200),
    schema_version: nonEmptyTextSchema.max(32),
    parent_pool: datasetReferenceSchema,
    source_repository: datasetReferenceSchema,
    persona_count: z.number().int().min(1).max(1_000_000),
    manifest_sha256: sha256DigestSchema,
    dataset_sha256: sha256DigestSchema,
    created_at: isoTimestampSchema,
  })
  .strict();

export const populationDatasetsResponseSchema = z
  .object({
    items: z.array(populationDatasetSummarySchema),
    total: z.number().int().nonnegative(),
  })
  .strict();

export const personaAttributeSchema = z
  .object({
    name: identifierTextSchema,
    value: nonEmptyTextSchema.max(500),
  })
  .strict();

export const personaSummarySchema = z
  .object({
    id: identifierSchema,
    dataset_id: identifierSchema,
    persona_id: identifierTextSchema,
    display_name: nonEmptyTextSchema.max(200),
    source: identifierTextSchema,
    profile_sha256: sha256DigestSchema,
    attributes: z.array(personaAttributeSchema),
  })
  .strict()
  .superRefine((persona, context) => {
    const attributeNames = persona.attributes.map((attribute) => attribute.name);

    if (new Set(attributeNames).size !== attributeNames.length) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["attributes"],
        message: "attribute names must be unique within a persona",
      });
    }

    const sortedAttributeNames = [...attributeNames].sort();

    if (attributeNames.some((name, index) => name !== sortedAttributeNames[index])) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["attributes"],
        message: "attributes must be sorted by name",
      });
    }
  });

export const populationPersonasResponseSchema = z
  .object({
    items: z.array(personaSummarySchema),
    page: z.number().int().positive(),
    page_size: z.number().int().min(1).max(100),
    total: z.number().int().nonnegative(),
  })
  .strict();

export const cohortDatasetSchema = z
  .object({
    id: identifierSchema,
    slug: datasetSlugSchema,
    dataset_sha256: sha256DigestSchema,
  })
  .strict();

export const cohortSummarySchema = z
  .object({
    id: identifierSchema,
    title: cohortTitleSchema,
    dataset: cohortDatasetSchema,
    persona_count: z.number().int().min(1).max(100),
    cohort_sha256: sha256DigestSchema,
    created_at: isoTimestampSchema,
  })
  .strict();

export const cohortMemberSchema = z
  .object({
    position: z.number().int().nonnegative().max(99),
    persona: personaSummarySchema,
  })
  .strict();

export const cohortDetailSchema = cohortSummarySchema
  .extend({
    members: z.array(cohortMemberSchema).min(1).max(100),
  })
  .strict()
  .superRefine((cohort, context) => {
    if (cohort.members.length !== cohort.persona_count) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["members"],
        message: "members length must equal persona_count",
      });
    }

    const positions = cohort.members.map((member) => member.position);

    if (positions.some((position, index) => position !== index)) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["members"],
        message: "member positions must be contiguous and start at zero",
      });
    }

    const memberIds = cohort.members.map((member) => member.persona.id);

    if (new Set(memberIds).size !== memberIds.length) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["members"],
        message: "persona identifiers must be unique within a cohort",
      });
    }

    if (cohort.members.some((member) => member.persona.dataset_id !== cohort.dataset.id)) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["members"],
        message: "every persona must belong to the cohort dataset",
      });
    }
  });

export const cohortsResponseSchema = z
  .object({
    items: z.array(cohortSummarySchema),
    total: z.number().int().nonnegative(),
  })
  .strict();

export const cohortCreateRequestSchema = z
  .object({
    title: cohortTitleSchema,
    dataset_id: identifierSchema,
    persona_ids: z.array(identifierSchema).min(1).max(100),
  })
  .strict()
  .superRefine((request, context) => {
    if (new Set(request.persona_ids).size !== request.persona_ids.length) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["persona_ids"],
        message: "persona identifiers must be unique",
      });
    }
  });

export const populationPersonasQuerySchema = z
  .object({
    q: z.string().trim().min(2).max(100).nullable(),
    page: z.number().int().positive(),
    pageSize: z.number().int().min(1).max(100),
  })
  .strict();

export type PopulationDatasetSummary = z.infer<typeof populationDatasetSummarySchema>;
export type PopulationDatasetsResponse = z.infer<typeof populationDatasetsResponseSchema>;
export type PersonaAttribute = z.infer<typeof personaAttributeSchema>;
export type PersonaSummary = z.infer<typeof personaSummarySchema>;
export type PopulationPersonasResponse = z.infer<typeof populationPersonasResponseSchema>;
export type CohortSummary = z.infer<typeof cohortSummarySchema>;
export type CohortDetail = z.infer<typeof cohortDetailSchema>;
export type CohortsResponse = z.infer<typeof cohortsResponseSchema>;
export type CohortCreateRequest = z.infer<typeof cohortCreateRequestSchema>;

export interface PopulationPersonasQuery {
  readonly q: string | null;
  readonly page: number;
  readonly pageSize: number;
}

export function createPopulationPersonasEndpoint(
  datasetId: string,
  query: PopulationPersonasQuery,
): string {
  const validatedDatasetId = identifierSchema.parse(datasetId);
  const validatedQuery = populationPersonasQuerySchema.parse(query);
  const parameters = new URLSearchParams({
    page: String(validatedQuery.page),
    page_size: String(validatedQuery.pageSize),
  });

  if (validatedQuery.q !== null) {
    parameters.set("q", validatedQuery.q);
  }

  return `${datasetsEndpoint}/${encodeURIComponent(validatedDatasetId)}/personas?${parameters.toString()}`;
}

export function createCohortDetailEndpoint(cohortId: string): string {
  const validatedCohortId = identifierSchema.parse(cohortId);

  return `${cohortsEndpoint}/${encodeURIComponent(validatedCohortId)}`;
}

export function fetchPopulationDatasets(
  signal: AbortSignal,
): Promise<PopulationDatasetsResponse> {
  return getJson(datasetsEndpoint, populationDatasetsResponseSchema, signal);
}

export function fetchPopulationPersonas(
  datasetId: string,
  query: PopulationPersonasQuery,
  signal: AbortSignal,
): Promise<PopulationPersonasResponse> {
  const endpoint = createPopulationPersonasEndpoint(datasetId, query);

  return getJson(endpoint, populationPersonasResponseSchema, signal);
}

export function fetchCohorts(signal: AbortSignal): Promise<CohortsResponse> {
  return getJson(cohortsEndpoint, cohortsResponseSchema, signal);
}

export function fetchCohortDetail(
  cohortId: string,
  signal: AbortSignal,
): Promise<CohortDetail> {
  const endpoint = createCohortDetailEndpoint(cohortId);

  return getJson(endpoint, cohortDetailSchema, signal);
}

export function createCohort(
  request: CohortCreateRequest,
  signal: AbortSignal,
): Promise<CohortDetail> {
  const validatedRequest = cohortCreateRequestSchema.parse(request);

  return postJson(cohortsEndpoint, validatedRequest, cohortDetailSchema, signal);
}
