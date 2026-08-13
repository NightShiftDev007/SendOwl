import { describe, expect, it } from "vitest";

import { mediaArticleSchema } from "./mediaContracts";
import {
  buildWorldModelCreateRequest,
  createWorldModelDetailEndpoint,
  evidenceWorldGraphSchema,
  semanticWorldGraphEvidenceTimelineSchema,
  semanticWorldGraphSliceSchema,
  semanticWorldGraphSchema,
  worldModelCreateRequestSchema,
  worldModelDetailSchema,
  worldModelSummarySchema,
} from "./worldModelContracts";

const worldModelId = "16f59066-b4e9-4d71-8c51-7742f85943f2";
const snapshotId = "33f6aee5-2912-4429-85ab-601dbfe41c19";
const articleId = "4fe5517f-6dd4-4376-8337-d94f50acc074";
const snapshotDigest = "a".repeat(64);
const contentDigest = "b".repeat(64);
const evidenceRevisionDigest = "c".repeat(64);

const currentArticle = mediaArticleSchema.parse({
  id: articleId,
  title: "关键行业发布季度经营数据",
  source_name: "Example News",
  published_at: "2026-08-12T04:30:00Z",
  excerpt: "报道记录了新的季度经营数据。",
  original_url: "https://example.com/articles/1",
  country_code: "CN",
  topic_id: "d70671a6-a681-49c0-aa03-194d38b82963",
  topic: "季度业绩",
  evidence_revision_sha256: evidenceRevisionDigest,
});

const validSnapshotSummary = {
  id: snapshotId,
  version: 1,
  evidence_count: 1,
  snapshot_sha256: snapshotDigest,
  created_at: "2026-08-12T08:30:00Z",
};

const validWorldModelDetail = {
  id: worldModelId,
  title: "季度经营媒体现实基线",
  created_at: "2026-08-12T08:30:00Z",
  snapshots: [validSnapshotSummary],
  latest_snapshot: {
    id: snapshotId,
    world_model_id: worldModelId,
    version: 1,
    verification: "human_confirmed",
    snapshot_sha256: snapshotDigest,
    created_at: "2026-08-12T08:30:00Z",
    evidence: [
      {
        article_id: articleId,
        source_name: "Example News",
        original_url: "https://example.com/articles/1",
        title: "关键行业发布季度经营数据",
        published_at: "2026-08-12T04:30:00Z",
        captured_at: "2026-08-12T08:30:00Z",
        country_code: "CN",
        excerpt: "报道记录了新的季度经营数据。",
        captured_text_sha256: contentDigest,
      },
    ],
  },
};

describe("world model contracts", () => {
  it("accepts an immutable generic-evidence detail and exact create request", () => {
    expect(worldModelDetailSchema.safeParse(validWorldModelDetail).success).toBe(true);
    expect(
      worldModelCreateRequestSchema.safeParse({
        title: "季度经营媒体现实基线",
        evidence: [{
          article_id: articleId,
          evidence_revision_sha256: evidenceRevisionDigest,
        }],
        verification: "human_confirmed",
      }).success,
    ).toBe(true);
  });

  it("builds evidence revisions directly from validated media articles", () => {
    expect(buildWorldModelCreateRequest("季度经营媒体现实基线", [currentArticle])).toEqual({
      title: "季度经营媒体现实基线",
      evidence: [{
        article_id: articleId,
        evidence_revision_sha256: evidenceRevisionDigest,
      }],
      verification: "human_confirmed",
    });
  });

  it("rejects duplicate evidence identities and removed company fields", () => {
    const selection = {
      article_id: articleId,
      evidence_revision_sha256: evidenceRevisionDigest,
    };

    expect(
      worldModelCreateRequestSchema.safeParse({
        title: "季度经营媒体现实基线",
        evidence: [selection, selection],
        verification: "human_confirmed",
      }).success,
    ).toBe(false);
    expect(
      worldModelCreateRequestSchema.safeParse({
        title: "季度经营媒体现实基线",
        company_id: "a4d8d10b-d7e5-4a34-b135-a6e6f1101834",
        evidence: [selection],
        verification: "human_confirmed",
      }).success,
    ).toBe(false);
    expect(
      worldModelSummarySchema.safeParse({
        ...validWorldModelDetail,
        company_name: "removed",
        latest_snapshot: validSnapshotSummary,
      }).success,
    ).toBe(false);
  });

  it("enforces evidence bounds and strict revision digests", () => {
    const oversizedEvidence = Array.from({ length: 51 }, (_, index) => ({
      article_id: `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
      evidence_revision_sha256: evidenceRevisionDigest,
    }));

    expect(
      worldModelCreateRequestSchema.safeParse({
        title: "季度经营媒体现实基线",
        evidence: oversizedEvidence,
        verification: "human_confirmed",
      }).success,
    ).toBe(false);
    expect(
      worldModelCreateRequestSchema.safeParse({
        title: "季度经营媒体现实基线",
        evidence: [{ article_id: articleId, evidence_revision_sha256: "not-a-digest" }],
        verification: "human_confirmed",
      }).success,
    ).toBe(false);
  });

  it("requires the latest detail to match history and be the highest version", () => {
    expect(
      worldModelDetailSchema.safeParse({
        ...validWorldModelDetail,
        latest_snapshot: {
          ...validWorldModelDetail.latest_snapshot,
          snapshot_sha256: "d".repeat(64),
        },
      }).success,
    ).toBe(false);
    expect(
      worldModelDetailSchema.safeParse({
        ...validWorldModelDetail,
        snapshots: [validSnapshotSummary, { ...validSnapshotSummary, id: "a27d8829-3cfb-4128-8791-cf4525e66741", version: 2 }],
      }).success,
    ).toBe(false);
  });

  it("encodes detail identifiers", () => {
    expect(createWorldModelDetailEndpoint("world/中国")).toBe(
      "/api/v2/world-models/world%2F%E4%B8%AD%E5%9B%BD",
    );
  });

  it("accepts only a connected self-hosted evidence graph", () => {
    const graphId = "c9403eb9-ec21-5d70-bccf-f417bf8f285d";
    const rootNodeId = "0f61c240-fcd8-574d-946d-a9f20a6fe083";
    const articleNodeId = "5d5440e9-a0f4-5cb4-98ec-e33112e119f0";
    const sourceNodeId = "bdef8f78-f6b2-5487-b6c5-10f39a12690f";
    const graph = {
      id: graphId,
      schema_version: "evidence-world-graph/v1",
      provider: "postgres_projection",
      world_model_id: worldModelId,
      snapshot_id: snapshotId,
      snapshot_sha256: snapshotDigest,
      graph_sha256: "f".repeat(64),
      nodes: [
        { id: rootNodeId, position: 0, kind: "world_snapshot", label: "Reality v1", detail: "1 article", article_id: null, country_code: null },
        { id: articleNodeId, position: 1, kind: "article", label: "Verified report", detail: "Evidence", article_id: articleId, country_code: null },
        { id: sourceNodeId, position: 2, kind: "source", label: "Example News", detail: null, article_id: null, country_code: null },
      ],
      edges: [
        { id: "4592e786-c5c4-52c5-a81d-61b6ca135660", position: 0, kind: "contains_evidence", source_node_id: rootNodeId, target_node_id: articleNodeId, article_id: articleId },
        { id: "229007b9-f9f8-5956-bce9-949e0740038a", position: 1, kind: "published_by", source_node_id: articleNodeId, target_node_id: sourceNodeId, article_id: articleId },
      ],
    };
    expect(evidenceWorldGraphSchema.safeParse(graph).success).toBe(true);
    expect(evidenceWorldGraphSchema.safeParse({
      ...graph,
      edges: [{ ...graph.edges[0], target_node_id: "9c3d8830-94fb-4c2c-8c30-349742bd6753" }, graph.edges[1]],
    }).success).toBe(false);
  });

  it("accepts only lifecycle-consistent evidence-backed semantic graphs", () => {
    const nodeId = "1db37e55-78ef-40fd-a69f-62caef841e1e";
    const succeeded = {
      id: "6a492f86-c24a-4017-abef-f7d47389df17",
      world_model_id: worldModelId,
      snapshot_id: snapshotId,
      snapshot_sha256: snapshotDigest,
      status: "succeeded",
      model_name: "qwen3.7-plus",
      semantic_config_sha256: "d".repeat(64),
      extraction_config_sha256: "e".repeat(64),
      prompt_schema_version: "world-graph-extraction/v1",
      input_sha256: "f".repeat(64),
      graph_sha256: "1".repeat(64),
      created_at: "2026-08-12T08:30:00Z",
      started_at: "2026-08-12T08:30:01Z",
      completed_at: "2026-08-12T08:30:03Z",
      nodes: [{
        id: nodeId,
        position: 0,
        entity_type: "policy",
        name: "绿色政策",
        summary: "正文明确提到的政策。",
        evidence: [{
          position: 0,
          article_id: articleId,
          quote: "政策😀",
          start_offset: 8,
          end_offset: 11,
        }],
      }],
      edges: [],
      error_code: null,
      error_message: null,
    };

    expect(semanticWorldGraphSchema.safeParse(succeeded).success).toBe(true);
    expect(semanticWorldGraphSchema.safeParse({
      ...succeeded,
      status: "failed",
      error_code: "provider_bad_request",
      error_message: "request rejected",
    }).success).toBe(false);
    expect(semanticWorldGraphSchema.safeParse({
      ...succeeded,
      nodes: [{
        ...succeeded.nodes[0]!,
        evidence: [{ ...succeeded.nodes[0]!.evidence[0]!, end_offset: 12 }],
      }],
    }).success).toBe(false);

    const slice = {
      graph_id: succeeded.id,
      graph_sha256: succeeded.graph_sha256,
      root_node_id: nodeId,
      direction: "both",
      hops: 2,
      max_nodes: 40,
      truncated: false,
      total_graph_node_count: 1,
      total_graph_edge_count: 0,
      nodes: succeeded.nodes,
      edges: [],
    };
    expect(semanticWorldGraphSliceSchema.safeParse(slice).success).toBe(true);
    expect(semanticWorldGraphSliceSchema.safeParse({
      ...slice,
      root_node_id: "a27d8829-3cfb-4128-8791-cf4525e66741",
    }).success).toBe(false);

    const timeline = {
      graph_id: succeeded.id,
      graph_sha256: succeeded.graph_sha256,
      temporal_semantics: "evidence_publication_time_not_fact_validity",
      items: [{
        position: 0,
        article_id: articleId,
        title: "关键行业发布季度经营数据",
        source_name: "Example News",
        published_at: "2026-08-12T04:30:00Z",
        captured_at: "2026-08-12T08:30:00Z",
        country_code: "CN",
        node_ids: [nodeId],
        edge_ids: [],
        evidence_reference_count: 1,
      }],
    };
    expect(semanticWorldGraphEvidenceTimelineSchema.safeParse(timeline).success).toBe(true);
    expect(semanticWorldGraphEvidenceTimelineSchema.safeParse({
      ...timeline,
      temporal_semantics: "fact_validity",
    }).success).toBe(false);
  });
});
