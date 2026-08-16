import { describe, expect, it } from "vitest";

import {
  policyDocumentCaptureRequestSchema,
  policyDocumentDetailSchema,
  policyVersionContentSchema,
} from "./policyEvidenceContracts";

const digest = "a".repeat(64);
const otherDigest = "b".repeat(64);
const source = {
  id: "2ce907de-4709-4eb6-b702-abac631607c7",
  authority_name: "Example Policy Authority",
  jurisdiction_code: "EX",
  homepage_url: "https://policy.example.gov/",
  source_sha256: digest,
  created_at: "2026-08-16T00:00:00Z",
} as const;
const version = {
  id: "ff51bd82-385d-48ad-aa3c-9277dd927380",
  version: 1,
  title: "Example Evidence Policy",
  original_url: "https://policy.example.gov/documents/17",
  language: "en",
  publication_date: "2026-08-01",
  effective_from: "2026-09-01",
  effective_until: null,
  captured_at: "2026-08-16T00:00:00Z",
  verification: "human_confirmed",
  content_sha256: digest,
  version_sha256: otherDigest,
} as const;

describe("Policy evidence contracts", () => {
  it("accepts a contiguous immutable Policy version history", () => {
    const detail = policyDocumentDetailSchema.parse({
      id: "af9b38d8-f040-4284-a1f5-b3e7ecf18066",
      source,
      canonical_identifier: "EX-2026-17",
      document_sha256: digest,
      created_at: "2026-08-16T00:00:00Z",
      version_count: 1,
      latest_version: version,
      versions: [version],
    });

    expect(detail.latest_version.effective_from).toBe("2026-09-01");
    expect(policyDocumentDetailSchema.safeParse({
      ...detail,
      version_count: 2,
    }).success).toBe(false);
  });

  it("rejects invalid effectivity and requires explicit human confirmation", () => {
    const request = {
      source: {
        authority_name: source.authority_name,
        jurisdiction_code: source.jurisdiction_code,
        homepage_url: source.homepage_url,
      },
      canonical_identifier: "EX-2026-17",
      title: version.title,
      original_url: version.original_url,
      language: version.language,
      publication_date: version.publication_date,
      effective_from: "2027-01-01",
      effective_until: "2026-12-31",
      captured_text: "Captured authoritative policy text.",
      verification: "human_confirmed",
    };

    expect(policyDocumentCaptureRequestSchema.safeParse(request).success).toBe(false);
    expect(policyDocumentCaptureRequestSchema.safeParse({
      ...request,
      effective_until: null,
      verification: "model_inferred",
    }).success).toBe(false);
  });

  it("keeps full Policy text behind a separate content contract", () => {
    expect(policyVersionContentSchema.parse({
      document_id: "af9b38d8-f040-4284-a1f5-b3e7ecf18066",
      version_id: version.id,
      captured_text: "Captured authoritative policy text.",
      content_sha256: digest,
    }).captured_text).toContain("authoritative");
  });
});
