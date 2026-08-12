import { describe, expect, it } from "vitest";

import {
  companyCoverageResponseSchema,
  companiesResponseSchema,
  createCompanyCoverageEndpoint,
  parseCompanyCreateRequest,
} from "./companyContracts";

const validCompany = {
  id: "1150f47c-e1fa-44b3-95a8-e9fc8d1338be",
  canonical_name: "星河科技有限公司",
  aliases: ["星河科技", "Galaxy Technology"],
  created_at: "2026-08-12T08:30:00Z",
};

const validArticle = {
  id: "f4a79dd2-cb53-4ab7-9e5b-25bbb1f0c27e",
  title: "星河科技发布季度经营数据",
  source_name: "Example News",
  published_at: "2026-08-12T04:30:00Z",
  excerpt: "星河科技发布了新的季度经营数据。",
  original_url: "https://example.com/articles/1",
  country_code: "CN",
  topic_id: "d70671a6-a681-49c0-aa03-194d38b82963",
  topic: "季度业绩",
};
const capturedTextDigest = "b".repeat(64);
const evidenceRevisionDigest = "c".repeat(64);

const validCoverageItem = {
  article: validArticle,
  captured_text_sha256: capturedTextDigest,
  evidence_revision_sha256: evidenceRevisionDigest,
  matched_aliases: ["星河科技"],
  evidence_contexts: [
    {
      alias: "星河科技",
      start_offset: 0,
      end_offset: 4,
      context: "星河科技发布了新的经营数据。",
    },
  ],
};

const validCoverageResponse = {
  company: validCompany,
  total_matching_articles: 1,
  source_count: 1,
  country_count: 1,
  topic_count: 1,
  items: [validCoverageItem],
  page: 1,
  page_size: 20,
};

describe("company contracts", () => {
  it("accepts a complete company list and rejects undeclared fields", () => {
    expect(
      companiesResponseSchema.safeParse({ items: [validCompany], total: 1 }).success,
    ).toBe(true);
    expect(
      companiesResponseSchema.safeParse({
        items: [validCompany],
        total: 1,
        source: "mock",
      }).success,
    ).toBe(false);
  });

  it("rejects evidence ranges that cannot identify source text", () => {
    const result = companyCoverageResponseSchema.safeParse({
      ...validCoverageResponse,
      items: [
        {
          ...validCoverageItem,
          evidence_contexts: [
            {
              alias: "星河科技",
              start_offset: 15,
              end_offset: 15,
              context: "报道提到星河科技发布了新的经营数据。",
            },
          ],
        },
      ],
    });

    expect(result.success).toBe(false);
  });

  it("requires lowercase content and evidence revision digests", () => {
    expect(companyCoverageResponseSchema.safeParse(validCoverageResponse).success).toBe(true);
    expect(
      companyCoverageResponseSchema.safeParse({
        ...validCoverageResponse,
        items: [{ ...validCoverageItem, captured_text_sha256: capturedTextDigest.toUpperCase() }],
      }).success,
    ).toBe(false);
    expect(
      companyCoverageResponseSchema.safeParse({
        ...validCoverageResponse,
        items: [{
          ...validCoverageItem,
          evidence_revision_sha256: evidenceRevisionDigest.toUpperCase(),
        }],
      }).success,
    ).toBe(false);
    expect(
      companyCoverageResponseSchema.safeParse({
        ...validCoverageResponse,
        items: [{
          article: validArticle,
          captured_text_sha256: capturedTextDigest,
          matched_aliases: validCoverageItem.matched_aliases,
          evidence_contexts: validCoverageItem.evidence_contexts,
        }],
      }).success,
    ).toBe(false);
  });
});

describe("company request parsing", () => {
  it("normalizes separators, removes duplicate aliases, and excludes the canonical name", () => {
    expect(
      parseCompanyCreateRequest(
        " 星河科技有限公司 ",
        "星河科技，Galaxy Technology\n galaxy technology, 星河科技有限公司",
      ),
    ).toEqual({
      canonical_name: "星河科技有限公司",
      aliases: ["星河科技", "Galaxy Technology"],
    });
  });

  it("rejects an empty canonical name", () => {
    expect(() => parseCompanyCreateRequest("  ", "星河科技")).toThrow();
  });

  it("encodes the company identifier and pagination", () => {
    const endpoint = createCompanyCoverageEndpoint("company/中国", 3, 20);
    const url = new URL(endpoint, "https://sandowl.test");

    expect(url.pathname).toBe("/api/v2/companies/company%2F%E4%B8%AD%E5%9B%BD/coverage");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      page: "3",
      page_size: "20",
    });
  });
});
