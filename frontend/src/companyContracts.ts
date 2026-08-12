import { z } from "zod";

import { getJson, postJson } from "./apiClient";
import { mediaArticleSchema } from "./mediaContracts";

const isoTimestampSchema = z.string().datetime({ offset: true });
const nonEmptyTextSchema = z.string().trim().min(1);
const companyNameSchema = nonEmptyTextSchema.max(300);
const companyIdentifierSchema = z.string().uuid();
const companyCoverageArticleSchema = mediaArticleSchema.strict();

export const sha256DigestSchema = z
  .string()
  .regex(/^[a-f0-9]{64}$/u, "Expected a lowercase SHA-256 digest");

export const companySchema = z
  .object({
    id: companyIdentifierSchema,
    canonical_name: companyNameSchema,
    aliases: z.array(companyNameSchema),
    created_at: isoTimestampSchema,
  })
  .strict();

export const companiesResponseSchema = z
  .object({
    items: z.array(companySchema),
    total: z.number().int().nonnegative(),
  })
  .strict();

export const companyCreateRequestSchema = z
  .object({
    canonical_name: companyNameSchema,
    aliases: z.array(companyNameSchema),
  })
  .strict();

export const evidenceContextSchema = z
  .object({
    alias: companyNameSchema,
    start_offset: z.number().int().nonnegative(),
    end_offset: z.number().int().positive(),
    context: nonEmptyTextSchema,
  })
  .strict()
  .superRefine((evidenceContext, refinementContext) => {
    if (evidenceContext.end_offset <= evidenceContext.start_offset) {
      refinementContext.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["end_offset"],
        message: "end_offset must be greater than start_offset",
      });
    }
  });

export const companyCoverageItemSchema = z
  .object({
    article: companyCoverageArticleSchema,
    captured_text_sha256: sha256DigestSchema,
    evidence_revision_sha256: sha256DigestSchema,
    matched_aliases: z.array(companyNameSchema).min(1),
    evidence_contexts: z.array(evidenceContextSchema).min(1),
  })
  .strict();

export const companyCoverageResponseSchema = z
  .object({
    company: companySchema,
    total_matching_articles: z.number().int().nonnegative(),
    source_count: z.number().int().nonnegative(),
    country_count: z.number().int().nonnegative(),
    topic_count: z.number().int().nonnegative(),
    items: z.array(companyCoverageItemSchema),
    page: z.number().int().positive(),
    page_size: z.number().int().min(1).max(100),
  })
  .strict();

export type Company = z.infer<typeof companySchema>;
export type CompaniesResponse = z.infer<typeof companiesResponseSchema>;
export type CompanyCreateRequest = z.infer<typeof companyCreateRequestSchema>;
export type EvidenceContext = z.infer<typeof evidenceContextSchema>;
export type CompanyCoverageItem = z.infer<typeof companyCoverageItemSchema>;
export type CompanyCoverageResponse = z.infer<typeof companyCoverageResponseSchema>;

const companiesEndpoint = "/api/v2/companies";

export function parseCompanyAliases(aliasesText: string): readonly string[] {
  const uniqueAliases = new Map<string, string>();

  for (const value of aliasesText.split(/[,，\n]+/u)) {
    const alias = value.trim();

    if (alias === "") {
      continue;
    }

    const comparisonKey = alias.toLocaleLowerCase("zh-CN");

    if (!uniqueAliases.has(comparisonKey)) {
      uniqueAliases.set(comparisonKey, alias);
    }
  }

  return [...uniqueAliases.values()];
}

export function parseCompanyCreateRequest(
  canonicalName: string,
  aliasesText: string,
): CompanyCreateRequest {
  const normalizedCanonicalName = canonicalName.trim();
  const canonicalComparisonKey = normalizedCanonicalName.toLocaleLowerCase("zh-CN");
  const aliases = parseCompanyAliases(aliasesText).filter(
    (alias) => alias.toLocaleLowerCase("zh-CN") !== canonicalComparisonKey,
  );

  return companyCreateRequestSchema.parse({
    canonical_name: normalizedCanonicalName,
    aliases,
  });
}

export function createCompanyCoverageEndpoint(
  companyId: string,
  page: number,
  pageSize: number,
): string {
  const parameters = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });

  return `/api/v2/companies/${encodeURIComponent(companyId)}/coverage?${parameters.toString()}`;
}

export function fetchCompanies(signal: AbortSignal): Promise<CompaniesResponse> {
  return getJson(companiesEndpoint, companiesResponseSchema, signal);
}

export function fetchCompanyCoverage(
  companyId: string,
  page: number,
  pageSize: number,
  signal: AbortSignal,
): Promise<CompanyCoverageResponse> {
  const endpoint = createCompanyCoverageEndpoint(companyId, page, pageSize);

  return getJson(endpoint, companyCoverageResponseSchema, signal);
}

export function createCompany(
  request: CompanyCreateRequest,
  signal: AbortSignal,
): Promise<Company> {
  const validatedRequest = companyCreateRequestSchema.parse(request);

  return postJson(companiesEndpoint, validatedRequest, companySchema, signal);
}
