import { describe, expect, it } from "vitest";

import { companyCoverageItemSchema } from "./companyContracts";
import {
  buildWorldModelCreateRequest,
  createWorldModelDetailEndpoint,
  worldModelCreateRequestSchema,
  worldModelDetailSchema,
  worldModelSummarySchema,
} from "./worldModelContracts";

const worldModelId = "16f59066-b4e9-4d71-8c51-7742f85943f2";
const companyId = "a4d8d10b-d7e5-4a34-b135-a6e6f1101834";
const snapshotId = "33f6aee5-2912-4429-85ab-601dbfe41c19";
const articleId = "4fe5517f-6dd4-4376-8337-d94f50acc074";
const anotherArticleId = "02e09ee8-88e8-4831-9427-f891255219ef";
const snapshotDigest = "a".repeat(64);
const contentDigest = "b".repeat(64);
const evidenceRevisionDigest = "c".repeat(64);
const evidenceSelection = {
  article_id: articleId,
  evidence_revision_sha256: evidenceRevisionDigest,
};

const currentCoverageItem = companyCoverageItemSchema.parse({
  article: {
    id: articleId,
    title: "星河科技发布季度经营数据",
    source_name: "Example News",
    published_at: "2026-08-12T04:30:00Z",
    excerpt: "星河科技发布了新的季度经营数据。",
    original_url: "https://example.com/articles/1",
    country_code: "CN",
    topic_id: "d70671a6-a681-49c0-aa03-194d38b82963",
    topic: "季度业绩",
  },
  captured_text_sha256: contentDigest,
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
});

const validSnapshotSummary = {
  id: snapshotId,
  version: 1,
  company_name: "星河科技有限公司",
  evidence_count: 1,
  snapshot_sha256: snapshotDigest,
  created_at: "2026-08-12T08:30:00Z",
};

const validWorldModelDetail = {
  id: worldModelId,
  title: "星河科技媒体现实基线",
  company_id: companyId,
  created_at: "2026-08-12T08:30:00Z",
  snapshots: [validSnapshotSummary],
  latest_snapshot: {
    id: snapshotId,
    world_model_id: worldModelId,
    version: 1,
    verification: "human_confirmed",
    snapshot_sha256: snapshotDigest,
    created_at: "2026-08-12T08:30:00Z",
    company: {
      id: companyId,
      canonical_name: "星河科技有限公司",
      aliases: ["星河科技", "Galaxy Technology"],
    },
    evidence: [
      {
        article_id: articleId,
        source_name: "Example News",
        original_url: "https://example.com/articles/1",
        title: "星河科技发布季度经营数据",
        published_at: "2026-08-12T04:30:00Z",
        captured_at: "2026-08-12T08:30:00Z",
        country_code: "CN",
        excerpt: "星河科技发布了新的季度经营数据。",
        captured_text_sha256: contentDigest,
        matched_aliases: ["星河科技"],
        evidence_contexts: [
          {
            alias: "星河科技",
            start_offset: 0,
            end_offset: 4,
            context: "星河科技发布了新的季度经营数据。",
          },
        ],
      },
    ],
  },
};

describe("world model contracts", () => {
  it("accepts a complete immutable detail and a human-confirmed create request", () => {
    expect(worldModelDetailSchema.safeParse(validWorldModelDetail).success).toBe(true);
    expect(
      worldModelCreateRequestSchema.safeParse({
        title: "星河科技媒体现实基线",
        company_id: companyId,
        evidence: [evidenceSelection],
        verification: "human_confirmed",
      }).success,
    ).toBe(true);
  });

  it("rejects duplicate evidence identities before posting", () => {
    const result = worldModelCreateRequestSchema.safeParse({
      title: "星河科技媒体现实基线",
      company_id: companyId,
      evidence: [
        evidenceSelection,
        { ...evidenceSelection, evidence_revision_sha256: "d".repeat(64) },
      ],
      verification: "human_confirmed",
    });

    expect(result.success).toBe(false);
  });

  it("enforces the 50-item boundary and strict evidence selection shape", () => {
    const oversizedEvidence = Array.from({ length: 51 }, (_, index) => ({
      article_id: `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
      evidence_revision_sha256: evidenceRevisionDigest,
    }));

    expect(
      worldModelCreateRequestSchema.safeParse({
        title: "星河科技媒体现实基线",
        company_id: companyId,
        evidence: oversizedEvidence,
        verification: "human_confirmed",
      }).success,
    ).toBe(false);
    expect(
      worldModelCreateRequestSchema.safeParse({
        title: "星河科技媒体现实基线",
        company_id: companyId,
        evidence: [{ article_id: articleId, captured_text_sha256: contentDigest }],
        verification: "human_confirmed",
      }).success,
    ).toBe(false);
    expect(
      worldModelCreateRequestSchema.safeParse({
        title: "星河科技媒体现实基线",
        company_id: companyId,
        evidence: [{ ...evidenceSelection, mutable: true }],
        verification: "human_confirmed",
      }).success,
    ).toBe(false);
  });

  it("builds the request from loaded coverage and rejects a stale selection", () => {
    expect(
      buildWorldModelCreateRequest(
        "星河科技媒体现实基线",
        companyId,
        [articleId],
        [currentCoverageItem],
      ),
    ).toEqual({
      title: "星河科技媒体现实基线",
      company_id: companyId,
      evidence: [evidenceSelection],
      verification: "human_confirmed",
    });
    expect(() =>
      buildWorldModelCreateRequest(
        "星河科技媒体现实基线",
        companyId,
        [anotherArticleId],
        [currentCoverageItem],
      ),
    ).toThrow(/不在当前已加载的企业证据响应中/u);
  });

  it("rejects a latest snapshot linked to another world model", () => {
    const result = worldModelDetailSchema.safeParse({
      ...validWorldModelDetail,
      latest_snapshot: {
        ...validWorldModelDetail.latest_snapshot,
        world_model_id: "a27d8829-3cfb-4128-8791-cf4525e66741",
      },
    });

    expect(result.success).toBe(false);
  });

  it("rejects oversized and multi-line model titles", () => {
    const oversizedTitle = "模".repeat(301);

    expect(
      worldModelCreateRequestSchema.safeParse({
        title: oversizedTitle,
        company_id: companyId,
        evidence: [evidenceSelection],
        verification: "human_confirmed",
      }).success,
    ).toBe(false);
    expect(
      worldModelCreateRequestSchema.safeParse({
        title: "星河科技\n媒体现实基线",
        company_id: companyId,
        evidence: [evidenceSelection],
        verification: "human_confirmed",
      }).success,
    ).toBe(false);
    expect(
      worldModelSummarySchema.safeParse({
        id: worldModelId,
        title: oversizedTitle,
        company_id: companyId,
        company_name: "星河科技有限公司",
        created_at: "2026-08-12T08:30:00Z",
        latest_snapshot: validSnapshotSummary,
      }).success,
    ).toBe(false);
  });

  it("rejects undeclared detail fields and encodes detail identifiers", () => {
    expect(
      worldModelDetailSchema.safeParse({
        ...validWorldModelDetail,
        mutable: true,
      }).success,
    ).toBe(false);
    expect(createWorldModelDetailEndpoint("world/model 中国")).toBe(
      "/api/v2/world-models/world%2Fmodel%20%E4%B8%AD%E5%9B%BD",
    );
  });
});
