import { afterEach, describe, expect, it, vi } from "vitest";

import { mediaArticleSchema } from "./mediaContracts";
import {
  appendWorldSnapshot,
  buildWorldSnapshotCreateRequest,
  buildWorldModelCreateRequest,
  createGraphPersonaCohort,
  createWorldModelDetailEndpoint,
  createWorldSnapshotEndpoint,
  evidenceWorldGraphSchema,
  graphPersonaCohortCreateRequestSchema,
  graphPersonaCohortCreationSchema,
  graphPersonaCohortOriginsResponseSchema,
  semanticWorldGraphEdgeHistorySchema,
  fetchWorldSnapshot,
  fetchGraphPersonaCohortOrigins,
  semanticWorldGraphEvidenceTimelineSchema,
  semanticWorldGraphPersonaMatchesSchema,
  semanticWorldGraphSearchResponseSchema,
  semanticWorldGraphSliceSchema,
  semanticWorldGraphSchema,
  worldModelCreateRequestSchema,
  worldModelDetailSchema,
  worldModelSummarySchema,
  worldSnapshotCreateRequestSchema,
} from "./worldModelContracts";

afterEach(() => {
  vi.restoreAllMocks();
});

const worldModelId = "16f59066-b4e9-4d71-8c51-7742f85943f2";
const snapshotId = "33f6aee5-2912-4429-85ab-601dbfe41c19";
const articleId = "4fe5517f-6dd4-4376-8337-d94f50acc074";
const snapshotDigest = "a".repeat(64);
const contentDigest = "b".repeat(64);
const evidenceRevisionDigest = "c".repeat(64);
const graphId = "c9403eb9-ec21-5d70-bccf-f417bf8f285d";
const nodeId = "0f61c240-fcd8-574d-946d-a9f20a6fe083";
const datasetId = "16f59066-b4e9-4d71-8c51-7742f85943f2";
const personaId = "02e09ee8-88e8-4831-9427-f891255219ef";
const cohortId = "6f22ff11-76ae-4a32-bc4b-7acd80efe19a";

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
    expect(buildWorldSnapshotCreateRequest([currentArticle])).toEqual({
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
      worldSnapshotCreateRequestSchema.safeParse({
        evidence: [selection, selection],
        verification: "human_confirmed",
      }).success,
    ).toBe(false);
    expect(
      worldSnapshotCreateRequestSchema.safeParse({
        title: "追加版本不允许改名",
        evidence: [selection],
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

  it("validates and posts one graph-guided Cohort with immutable lineage", async () => {
    const request = {
      title: "港口政策观察候选组",
      dataset_id: datasetId,
      persona_ids: [personaId],
    };
    const cohort = {
      id: cohortId,
      title: request.title,
      dataset: {
        id: datasetId,
        slug: "matraix-zh-v1",
        dataset_sha256: "d".repeat(64),
      },
      persona_count: 1,
      cohort_sha256: "e".repeat(64),
      created_at: "2026-08-12T09:00:00Z",
      members: [{
        position: 0,
        persona: {
          id: personaId,
          dataset_id: datasetId,
          persona_id: "persona.cn.0001",
          display_name: "陈晓雯",
          source: "matraix.public",
          profile_sha256: "f".repeat(64),
          attributes: [{ name: "region", value: "华东" }],
        },
      }],
    };
    const response = {
      origin: {
        id: "c82e1f42-b4a3-4564-a255-e4752fd46216",
        graph_id: graphId,
        graph_sha256: "1".repeat(64),
        node_id: nodeId,
        dataset: cohort.dataset,
        cohort_id: cohortId,
        cohort_sha256: cohort.cohort_sha256,
        match_semantics: "exact_token_overlap_non_low_information_attributes",
        matcher_version: "1.0.0",
        selected_persona_ids: [personaId],
        origin_sha256: "2".repeat(64),
        created_at: "2026-08-12T09:00:00Z",
      },
      cohort,
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(response), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );

    expect(graphPersonaCohortCreateRequestSchema.safeParse(request).success).toBe(true);
    expect(graphPersonaCohortCreationSchema.safeParse(response).success).toBe(true);
    await expect(
      createGraphPersonaCohort(graphId, nodeId, request, new AbortController().signal),
    ).resolves.toEqual(response);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      `/api/v2/world-graphs/${graphId}/nodes/${nodeId}/cohorts`,
    );
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({
      method: "POST",
      body: JSON.stringify(request),
    });
    expect(
      graphPersonaCohortCreationSchema.safeParse({
        ...response,
        origin: { ...response.origin, selected_persona_ids: [] },
      }).success,
    ).toBe(false);
  });

  it("rejects graph-guided Cohort selections larger than the verified candidate bound", () => {
    expect(
      graphPersonaCohortCreateRequestSchema.safeParse({
        title: "过大候选组",
        dataset_id: datasetId,
        persona_ids: Array.from(
          { length: 9 },
          (_, index) => `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
        ),
      }).success,
    ).toBe(false);
  });

  it("reads a bounded graph-origin page and rejects cross-Cohort lineage", async () => {
    const origin = {
      id: "c82e1f42-b4a3-4564-a255-e4752fd46216",
      graph_id: graphId,
      graph_sha256: "1".repeat(64),
      node_id: nodeId,
      dataset: {
        id: datasetId,
        slug: "matraix-zh-v1",
        dataset_sha256: "d".repeat(64),
      },
      cohort_id: cohortId,
      cohort_sha256: "e".repeat(64),
      match_semantics: "exact_token_overlap_non_low_information_attributes",
      matcher_version: "1.0.0",
      selected_persona_ids: [personaId],
      origin_sha256: "2".repeat(64),
      created_at: "2026-08-12T09:00:00Z",
    };
    const response = { items: [origin], page: 1, page_size: 5, total: 1 };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(response), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    expect(graphPersonaCohortOriginsResponseSchema.safeParse(response).success).toBe(true);
    await expect(
      fetchGraphPersonaCohortOrigins(cohortId, 1, 5, new AbortController().signal),
    ).resolves.toEqual(response);
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      `/api/v2/populations/cohorts/${cohortId}/graph-origins?page=1&page_size=5`,
    );
    expect(
      graphPersonaCohortOriginsResponseSchema.safeParse({
        ...response,
        items: [{ ...origin, cohort_id: worldModelId }, origin],
        total: 2,
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
    expect(createWorldSnapshotEndpoint("world/中国", "snapshot/第二版")).toBe(
      "/api/v2/world-models/world%2F%E4%B8%AD%E5%9B%BD/snapshots/snapshot%2F%E7%AC%AC%E4%BA%8C%E7%89%88",
    );
    expect(createWorldSnapshotEndpoint("world/中国", null)).toBe(
      "/api/v2/world-models/world%2F%E4%B8%AD%E5%9B%BD/snapshots",
    );
  });

  it("appends one exact revision selection with a single non-retried POST", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(validWorldModelDetail.latest_snapshot), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const request = buildWorldSnapshotCreateRequest([currentArticle]);

    await expect(
      appendWorldSnapshot(worldModelId, request, new AbortController().signal),
    ).resolves.toEqual(validWorldModelDetail.latest_snapshot);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      `/api/v2/world-models/${worldModelId}/snapshots`,
    );
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({
      method: "POST",
      body: JSON.stringify(request),
    });
  });

  it("rejects a historical snapshot payload from another requested identity", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({
        ...validWorldModelDetail.latest_snapshot,
        id: "a27d8829-3cfb-4128-8791-cf4525e66741",
      }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(
      fetchWorldSnapshot(worldModelId, snapshotId, new AbortController().signal),
    ).rejects.toThrow("snapshot must match the requested snapshot identifier");
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

    const edgeId = "45adf86e-bbc4-478b-8d5d-b927e5f0a4bd";
    const edgeHistory = {
      graph_id: succeeded.id,
      graph_sha256: succeeded.graph_sha256,
      edge_id: edgeId,
      observation_semantics: "cross_snapshot_exact_signature_not_fact_validity",
      signature: {
        source_entity_type: "organization",
        source_name: "Example Council",
        relation_type: "announced",
        target_entity_type: "policy",
        target_name: "Green Policy",
        fact: "Example Council announced Green Policy.",
      },
      inspected_graph_count: 1,
      total_succeeded_graph_count: 1,
      truncated: false,
      items: [{
        position: 0,
        graph_id: succeeded.id,
        graph_sha256: succeeded.graph_sha256,
        graph_created_at: succeeded.created_at,
        graph_completed_at: succeeded.completed_at,
        snapshot_id: succeeded.snapshot_id,
        snapshot_sha256: succeeded.snapshot_sha256,
        snapshot_version: 1,
        edge_id: edgeId,
        evidence_article_ids: [articleId],
        evidence_published_from: "2026-08-12T04:30:00Z",
        evidence_published_through: "2026-08-12T04:30:00Z",
      }],
      limitations: [
        "Exact signatures only.",
        "Publication is not validity.",
        "Missing is not invalidation.",
      ],
    };
    expect(semanticWorldGraphEdgeHistorySchema.safeParse(edgeHistory).success).toBe(true);
    expect(semanticWorldGraphEdgeHistorySchema.safeParse({
      ...edgeHistory,
      observation_semantics: "fact_validity",
    }).success).toBe(false);

    const datasetId = "c9ee349c-20d3-40b4-b23f-a82c661dd2cd";
    const personaId = "586e5f5e-9500-4f17-b350-c89feab54d55";
    const personaMatches = {
      graph_id: succeeded.id,
      graph_sha256: succeeded.graph_sha256,
      node_id: nodeId,
      dataset: {
        id: datasetId,
        slug: "matraix-persona-dev-sample",
        dataset_sha256: "2".repeat(64),
      },
      match_semantics: "exact_token_overlap_non_low_information_attributes",
      query_terms: ["绿色政策"],
      inspected_persona_count: 1,
      dataset_persona_count: 1,
      scan_truncated: false,
      total_match_count_in_scan: 1,
      matches: [{
        position: 0,
        score: 1,
        matched_terms: ["绿色政策"],
        matched_attributes: [{ name: "policy_interest", value: "绿色政策" }],
        persona: {
          id: personaId,
          dataset_id: datasetId,
          persona_id: "persona-policy-1",
          display_name: "政策关注 Persona",
          source: "matraix",
          profile_sha256: "3".repeat(64),
          attributes: [{ name: "policy_interest", value: "绿色政策" }],
        },
      }],
      limitations: [
        "Exact tokens only.",
        "Candidates do not imply stance.",
        "The scan is bounded.",
      ],
    };
    expect(semanticWorldGraphPersonaMatchesSchema.safeParse(personaMatches).success).toBe(true);
    expect(semanticWorldGraphPersonaMatchesSchema.safeParse({
      ...personaMatches,
      matches: [{ ...personaMatches.matches[0], score: 2 }],
    }).success).toBe(false);
    expect(semanticWorldGraphPersonaMatchesSchema.safeParse({
      ...personaMatches,
      dataset: { ...personaMatches.dataset, id: worldModelId },
    }).success).toBe(false);

    const search = {
      graph_id: succeeded.id,
      graph_sha256: succeeded.graph_sha256,
      query: "绿色政策",
      search_semantics: "casefolded_lexical_substring",
      total_match_count: 1,
      truncated: false,
      results: [{
        kind: "node",
        rank: 0,
        matched_fields: ["name", "summary"],
        node: succeeded.nodes[0],
      }],
      limitations: [
        "Search is deterministic lexical matching.",
        "Results retain exact evidence quotes.",
      ],
    };
    expect(semanticWorldGraphSearchResponseSchema.safeParse(search).success).toBe(true);
    expect(semanticWorldGraphSearchResponseSchema.safeParse({
      ...search,
      total_match_count: 2,
      truncated: false,
    }).success).toBe(false);
  });
});
