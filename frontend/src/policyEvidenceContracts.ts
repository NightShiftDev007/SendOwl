import { z } from "zod";

import { getJson, postJson } from "./apiClient";
import { sha256DigestSchema } from "./mediaContracts";

const endpoint = "/api/v2/policy-documents";
const uuidSchema = z.string().uuid();
const timestampSchema = z.string().datetime({ offset: true });
const dateSchema = z.string().regex(/^\d{4}-\d{2}-\d{2}$/u);
const urlSchema = z.string().url().regex(/^https?:\/\//u);
const textSchema = z.string().trim().min(1);
const languageSchema = z.string().regex(/^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/u);
const verificationSchema = z.literal("human_confirmed");

export const policySourceSchema = z.object({
  id: uuidSchema,
  authority_name: textSchema.max(300).regex(/^[^\r\n]+$/u),
  jurisdiction_code: z.string().regex(/^[A-Z0-9][A-Z0-9-]{1,15}$/u),
  homepage_url: urlSchema,
  source_sha256: sha256DigestSchema,
  created_at: timestampSchema,
}).strict();

export const policyVersionSummarySchema = z.object({
  id: uuidSchema,
  version: z.number().int().min(1).max(100),
  title: textSchema.max(500).regex(/^[^\r\n]+$/u),
  original_url: urlSchema,
  language: languageSchema,
  publication_date: dateSchema,
  effective_from: dateSchema.nullable(),
  effective_until: dateSchema.nullable(),
  captured_at: timestampSchema,
  verification: verificationSchema,
  content_sha256: sha256DigestSchema,
  version_sha256: sha256DigestSchema,
}).strict().superRefine((version, context) => {
  if (version.effective_from !== null && version.effective_until !== null
    && version.effective_until <= version.effective_from) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["effective_until"],
      message: "Policy effective_until must follow effective_from",
    });
  }
});

const policyDocumentSummaryObjectSchema = z.object({
  id: uuidSchema,
  source: policySourceSchema,
  canonical_identifier: textSchema.max(256).regex(/^[^\r\n]+$/u),
  document_sha256: sha256DigestSchema,
  created_at: timestampSchema,
  version_count: z.number().int().min(1).max(100),
  latest_version: policyVersionSummarySchema,
}).strict();

export const policyDocumentSummarySchema = policyDocumentSummaryObjectSchema.superRefine(
  (document, context) => {
    if (document.latest_version.version !== document.version_count) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["latest_version"],
        message: "Latest Policy version must equal version_count",
      });
    }
  },
);

export const policyDocumentDetailSchema = policyDocumentSummaryObjectSchema.extend({
  versions: z.array(policyVersionSummarySchema).min(1).max(100),
}).strict().superRefine((document, context) => {
  const contiguous = document.versions.every((version, index) => version.version === index + 1);
  const latest = document.versions.at(-1);
  if (!contiguous || document.versions.length !== document.version_count
    || latest?.id !== document.latest_version.id) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["versions"],
      message: "Policy version history must be contiguous and match the latest version",
    });
  }
});

export const policyDocumentsResponseSchema = z.object({
  items: z.array(policyDocumentSummarySchema).max(50),
  page: z.number().int().positive(),
  page_size: z.number().int().min(1).max(50),
  total: z.number().int().nonnegative(),
}).strict();

export const policyVersionContentSchema = z.object({
  document_id: uuidSchema,
  version_id: uuidSchema,
  captured_text: z.string().min(1).max(2_000_000),
  content_sha256: sha256DigestSchema,
}).strict();

export const policyDocumentCaptureRequestSchema = z.object({
  source: z.object({
    authority_name: textSchema.max(300).regex(/^[^\r\n]+$/u),
    jurisdiction_code: z.string().regex(/^[A-Z0-9][A-Z0-9-]{1,15}$/u),
    homepage_url: urlSchema,
  }).strict(),
  canonical_identifier: textSchema.max(256).regex(/^[^\r\n]+$/u),
  title: textSchema.max(500).regex(/^[^\r\n]+$/u),
  original_url: urlSchema,
  language: languageSchema,
  publication_date: dateSchema,
  effective_from: dateSchema.nullable(),
  effective_until: dateSchema.nullable(),
  captured_text: z.string().min(1).max(2_000_000),
  verification: verificationSchema,
}).strict().superRefine((request, context) => {
  if (request.effective_from !== null && request.effective_until !== null
    && request.effective_until <= request.effective_from) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["effective_until"],
      message: "Policy effective_until must follow effective_from",
    });
  }
});

export type PolicyDocumentSummary = z.infer<typeof policyDocumentSummarySchema>;
export type PolicyDocumentDetail = z.infer<typeof policyDocumentDetailSchema>;
export type PolicyVersionContent = z.infer<typeof policyVersionContentSchema>;
export type PolicyDocumentCaptureRequest = z.infer<typeof policyDocumentCaptureRequestSchema>;

export function fetchPolicyDocuments(
  page: number,
  signal: AbortSignal,
): Promise<z.infer<typeof policyDocumentsResponseSchema>> {
  const parsedPage = z.number().int().positive().parse(page);
  return getJson(
    `${endpoint}?page=${parsedPage}&page_size=20`,
    policyDocumentsResponseSchema,
    signal,
  );
}

export function fetchPolicyDocument(
  documentId: string,
  signal: AbortSignal,
): Promise<PolicyDocumentDetail> {
  const id = uuidSchema.parse(documentId);
  return getJson(`${endpoint}/${encodeURIComponent(id)}`, policyDocumentDetailSchema, signal);
}

export function fetchPolicyVersionContent(
  documentId: string,
  versionId: string,
  signal: AbortSignal,
): Promise<PolicyVersionContent> {
  const document = uuidSchema.parse(documentId);
  const version = uuidSchema.parse(versionId);
  return getJson(
    `${endpoint}/${encodeURIComponent(document)}/versions/${encodeURIComponent(version)}/content`,
    policyVersionContentSchema,
    signal,
  );
}

export function capturePolicyDocument(
  request: PolicyDocumentCaptureRequest,
  signal: AbortSignal,
): Promise<PolicyDocumentDetail> {
  return postJson(
    endpoint,
    policyDocumentCaptureRequestSchema.parse(request),
    policyDocumentDetailSchema,
    signal,
  );
}
