import { z } from "zod";

import { getJson, postJson } from "./apiClient";
import { sha256DigestSchema, type MediaArticle } from "./mediaContracts";

const worldModelsEndpoint = "/api/v2/world-models";
const identifierSchema = z.string().uuid();
const isoTimestampSchema = z.string().datetime({ offset: true });
const nonEmptyTextSchema = z.string().trim().min(1);
const worldModelTitleSchema = nonEmptyTextSchema
  .max(300)
  .regex(/^[^\r\n]+$/u, "World model title must be a single line");
const httpUrlSchema = z
  .string()
  .url()
  .refine((value) => {
    const protocol = new URL(value).protocol;

    return protocol === "http:" || protocol === "https:";
  }, "Expected an HTTP or HTTPS URL");

export const snapshotSummarySchema = z
  .object({
    id: identifierSchema,
    version: z.number().int().positive(),
    evidence_count: z.number().int().min(1).max(50),
    snapshot_sha256: sha256DigestSchema,
    created_at: isoTimestampSchema,
  })
  .strict();

export const worldModelSummarySchema = z
  .object({
    id: identifierSchema,
    title: worldModelTitleSchema,
    created_at: isoTimestampSchema,
    latest_snapshot: snapshotSummarySchema,
  })
  .strict();

export const worldModelsResponseSchema = z
  .object({
    items: z.array(worldModelSummarySchema),
    total: z.number().int().nonnegative(),
  })
  .strict();

export const snapshotEvidenceSchema = z
  .object({
    article_id: identifierSchema,
    source_name: nonEmptyTextSchema,
    original_url: httpUrlSchema,
    title: nonEmptyTextSchema,
    published_at: isoTimestampSchema,
    captured_at: isoTimestampSchema,
    country_code: z.string().regex(/^[A-Z]{2}$/u).nullable(),
    excerpt: nonEmptyTextSchema.max(280),
    captured_text_sha256: sha256DigestSchema,
  })
  .strict();

export const snapshotDetailSchema = z
  .object({
    id: identifierSchema,
    world_model_id: identifierSchema,
    version: z.number().int().positive(),
    verification: z.literal("human_confirmed"),
    snapshot_sha256: sha256DigestSchema,
    created_at: isoTimestampSchema,
    evidence: z.array(snapshotEvidenceSchema).min(1).max(50),
  })
  .strict();

export const worldModelDetailSchema = z
  .object({
    id: identifierSchema,
    title: worldModelTitleSchema,
    created_at: isoTimestampSchema,
    snapshots: z.array(snapshotSummarySchema).min(1),
    latest_snapshot: snapshotDetailSchema,
  })
  .strict()
  .superRefine((worldModel, context) => {
    if (worldModel.latest_snapshot.world_model_id !== worldModel.id) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["latest_snapshot", "world_model_id"],
        message: "latest_snapshot must belong to the enclosing world model",
      });
    }

    const matchingSummaries = worldModel.snapshots.filter(
      (snapshot) => snapshot.id === worldModel.latest_snapshot.id,
    );
    const latestSummary = matchingSummaries[0];

    if (
      matchingSummaries.length !== 1
      || latestSummary === undefined
      || latestSummary.version !== worldModel.latest_snapshot.version
      || latestSummary.snapshot_sha256 !== worldModel.latest_snapshot.snapshot_sha256
      || latestSummary.evidence_count !== worldModel.latest_snapshot.evidence.length
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["latest_snapshot"],
        message: "latest_snapshot must match its snapshot summary",
      });
    }

    const highestVersion = Math.max(
      ...worldModel.snapshots.map((snapshot) => snapshot.version),
    );

    if (worldModel.latest_snapshot.version !== highestVersion) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["latest_snapshot", "version"],
        message: "latest_snapshot must be the highest snapshot version",
      });
    }
  });

export const worldModelEvidenceSelectionSchema = z
  .object({
    article_id: identifierSchema,
    evidence_revision_sha256: sha256DigestSchema,
  })
  .strict();

export const worldModelCreateRequestSchema = z
  .object({
    title: worldModelTitleSchema,
    evidence: z.array(worldModelEvidenceSelectionSchema).min(1).max(50),
    verification: z.literal("human_confirmed"),
  })
  .strict()
  .superRefine((request, context) => {
    const articleIds = request.evidence.map((selection) => selection.article_id);

    if (new Set(articleIds).size !== articleIds.length) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["evidence"],
        message: "evidence article_id values must not contain duplicates",
      });
    }
  });

const evidenceGraphNodeKindSchema = z.enum(["world_snapshot", "article", "source", "country"]);
const evidenceGraphEdgeKindSchema = z.enum(["contains_evidence", "published_by", "located_in"]);

export const evidenceWorldGraphNodeSchema = z
  .object({
    id: identifierSchema,
    position: z.number().int().nonnegative(),
    kind: evidenceGraphNodeKindSchema,
    label: nonEmptyTextSchema.max(300),
    detail: nonEmptyTextSchema.max(280).nullable(),
    article_id: identifierSchema.nullable(),
    country_code: z.string().regex(/^[A-Z]{2}$/u).nullable(),
  })
  .strict()
  .superRefine((node, context) => {
    if ((node.kind === "article") !== (node.article_id !== null)) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["article_id"],
        message: "article_id must be present only for article nodes",
      });
    }
    if ((node.kind === "country") !== (node.country_code !== null)) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["country_code"],
        message: "country_code must be present only for country nodes",
      });
    }
  });

export const evidenceWorldGraphEdgeSchema = z
  .object({
    id: identifierSchema,
    position: z.number().int().nonnegative(),
    kind: evidenceGraphEdgeKindSchema,
    source_node_id: identifierSchema,
    target_node_id: identifierSchema,
    article_id: identifierSchema,
  })
  .strict();

export const evidenceWorldGraphSchema = z
  .object({
    id: identifierSchema,
    schema_version: z.literal("evidence-world-graph/v1"),
    provider: z.literal("postgres_projection"),
    world_model_id: identifierSchema,
    snapshot_id: identifierSchema,
    snapshot_sha256: sha256DigestSchema,
    graph_sha256: sha256DigestSchema,
    nodes: z.array(evidenceWorldGraphNodeSchema).min(3),
    edges: z.array(evidenceWorldGraphEdgeSchema).min(2),
  })
  .strict()
  .superRefine((graph, context) => {
    const nodeIds = new Set(graph.nodes.map((node) => node.id));
    const contiguousNodes = graph.nodes.every((node, index) => node.position === index);
    const contiguousEdges = graph.edges.every((edge, index) => edge.position === index);
    const connectedEdges = graph.edges.every(
      (edge) => nodeIds.has(edge.source_node_id) && nodeIds.has(edge.target_node_id),
    );
    if (nodeIds.size !== graph.nodes.length || !contiguousNodes || !contiguousEdges || !connectedEdges) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "evidence world graph contains duplicate, non-contiguous, or dangling records",
      });
    }
  });

const semanticWorldGraphStatusSchema = z.enum(["queued", "running", "succeeded", "failed"]);
const semanticWorldGraphEntityTypeSchema = z.enum([
  "organization",
  "person",
  "location",
  "policy",
  "event",
  "concept",
]);

export const semanticWorldGraphEvidenceSchema = z
  .object({
    position: z.number().int().min(0).max(19),
    article_id: identifierSchema,
    quote: nonEmptyTextSchema.max(500),
    start_offset: z.number().int().nonnegative(),
    end_offset: z.number().int().positive(),
  })
  .strict()
  .refine(
    (evidence) => evidence.end_offset - evidence.start_offset === Array.from(evidence.quote).length,
    "Semantic graph evidence offsets must span the exact quote",
  );

export const semanticWorldGraphNodeSchema = z
  .object({
    id: identifierSchema,
    position: z.number().int().min(0).max(499),
    entity_type: semanticWorldGraphEntityTypeSchema,
    name: nonEmptyTextSchema.max(200),
    summary: nonEmptyTextSchema.max(500),
    evidence: z.array(semanticWorldGraphEvidenceSchema).min(1).max(20),
  })
  .strict();

export const semanticWorldGraphEdgeSchema = z
  .object({
    id: identifierSchema,
    position: z.number().int().min(0).max(1999),
    source_node_id: identifierSchema,
    target_node_id: identifierSchema,
    relation_type: z.string().regex(/^[a-z][a-z0-9_]{0,63}$/u),
    fact: nonEmptyTextSchema.max(500),
    evidence: z.array(semanticWorldGraphEvidenceSchema).min(1).max(20),
  })
  .strict();

export const semanticWorldGraphSchema = z
  .object({
    id: identifierSchema,
    world_model_id: identifierSchema,
    snapshot_id: identifierSchema,
    snapshot_sha256: sha256DigestSchema,
    status: semanticWorldGraphStatusSchema,
    model_name: nonEmptyTextSchema.max(200),
    semantic_config_sha256: sha256DigestSchema,
    extraction_config_sha256: sha256DigestSchema,
    prompt_schema_version: z.literal("world-graph-extraction/v1"),
    input_sha256: sha256DigestSchema,
    graph_sha256: sha256DigestSchema.nullable(),
    created_at: isoTimestampSchema,
    started_at: isoTimestampSchema.nullable(),
    completed_at: isoTimestampSchema.nullable(),
    nodes: z.array(semanticWorldGraphNodeSchema).max(500),
    edges: z.array(semanticWorldGraphEdgeSchema).max(2000),
    error_code: z.string().regex(/^[a-z][a-z0-9_]{0,127}$/u).nullable(),
    error_message: nonEmptyTextSchema.max(500).nullable(),
  })
  .strict()
  .superRefine((graph, context) => {
    const nodeIds = new Set(graph.nodes.map((node) => node.id));
    const recordsAreValid = graph.nodes.every((node, index) => node.position === index)
      && graph.edges.every((edge, index) => edge.position === index)
      && nodeIds.size === graph.nodes.length
      && graph.edges.every(
        (edge) => nodeIds.has(edge.source_node_id) && nodeIds.has(edge.target_node_id),
      );
    const isSucceeded = graph.status === "succeeded";
    const isFailed = graph.status === "failed";
    const lifecycleIsValid = graph.status === "queued"
      ? graph.started_at === null && graph.completed_at === null
      : graph.status === "running"
        ? graph.started_at !== null && graph.completed_at === null
        : graph.started_at !== null && graph.completed_at !== null;
    const resultIsValid = isSucceeded
      ? graph.graph_sha256 !== null
        && graph.nodes.length > 0
        && graph.error_code === null
        && graph.error_message === null
      : graph.graph_sha256 === null && graph.nodes.length === 0 && graph.edges.length === 0;
    const failureIsValid = isFailed
      ? graph.error_code !== null && graph.error_message !== null
      : graph.error_code === null && graph.error_message === null;
    if (!recordsAreValid || !lifecycleIsValid || !resultIsValid || !failureIsValid) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Semantic world graph lifecycle or normalized records are inconsistent",
      });
    }
  });

export const semanticWorldGraphsResponseSchema = z
  .object({
    items: z.array(semanticWorldGraphSchema),
    total: z.number().int().nonnegative(),
  })
  .strict();

export const semanticWorldGraphSliceDirectionSchema = z.enum(["both", "outbound", "inbound"]);

export const semanticWorldGraphSliceSchema = z
  .object({
    graph_id: identifierSchema,
    graph_sha256: sha256DigestSchema,
    root_node_id: identifierSchema,
    direction: semanticWorldGraphSliceDirectionSchema,
    hops: z.number().int().min(1).max(3),
    max_nodes: z.number().int().min(2).max(100),
    truncated: z.boolean(),
    total_graph_node_count: z.number().int().min(1).max(500),
    total_graph_edge_count: z.number().int().min(0).max(2000),
    nodes: z.array(semanticWorldGraphNodeSchema).min(1).max(100),
    edges: z.array(semanticWorldGraphEdgeSchema).max(2000),
  })
  .strict()
  .superRefine((slice, context) => {
    const nodeIds = new Set(slice.nodes.map((node) => node.id));
    const edgeIds = new Set(slice.edges.map((edge) => edge.id));
    const isConnected = slice.edges.every(
      (edge) => nodeIds.has(edge.source_node_id) && nodeIds.has(edge.target_node_id),
    );
    if (
      !nodeIds.has(slice.root_node_id)
      || nodeIds.size !== slice.nodes.length
      || edgeIds.size !== slice.edges.length
      || !isConnected
      || slice.nodes.length > slice.total_graph_node_count
      || slice.edges.length > slice.total_graph_edge_count
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Semantic world graph slice contains inconsistent graph records",
      });
    }
  });

export const semanticWorldGraphTimelineItemSchema = z
  .object({
    position: z.number().int().min(0).max(49),
    article_id: identifierSchema,
    title: nonEmptyTextSchema,
    source_name: nonEmptyTextSchema,
    published_at: isoTimestampSchema,
    captured_at: isoTimestampSchema,
    country_code: z.string().regex(/^[A-Z]{2}$/u).nullable(),
    node_ids: z.array(identifierSchema).max(500),
    edge_ids: z.array(identifierSchema).max(2000),
    evidence_reference_count: z.number().int().min(1).max(50000),
  })
  .strict()
  .refine(
    (item) => item.node_ids.length > 0 || item.edge_ids.length > 0,
    "Timeline item must reference a node or edge",
  )
  .refine(
    (item) => new Set(item.node_ids).size === item.node_ids.length
      && new Set(item.edge_ids).size === item.edge_ids.length,
    "Timeline object IDs must be unique",
  );

export const semanticWorldGraphEvidenceTimelineSchema = z
  .object({
    graph_id: identifierSchema,
    graph_sha256: sha256DigestSchema,
    temporal_semantics: z.literal("evidence_publication_time_not_fact_validity"),
    items: z.array(semanticWorldGraphTimelineItemSchema).min(1).max(50),
  })
  .strict()
  .superRefine((timeline, context) => {
    const positionsAreContiguous = timeline.items.every((item, index) => item.position === index);
    const articleIds = new Set(timeline.items.map((item) => item.article_id));
    const orderedTimes = timeline.items.map((item) => Date.parse(item.published_at));
    const timesAreAscending = orderedTimes.every(
      (value, index) => index === 0 || value >= (orderedTimes[index - 1] ?? value),
    );
    if (!positionsAreContiguous || articleIds.size !== timeline.items.length || !timesAreAscending) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Semantic world graph evidence timeline is inconsistent",
      });
    }
  });

export type SnapshotSummary = z.infer<typeof snapshotSummarySchema>;
export type WorldModelSummary = z.infer<typeof worldModelSummarySchema>;
export type WorldModelsResponse = z.infer<typeof worldModelsResponseSchema>;
export type SnapshotEvidence = z.infer<typeof snapshotEvidenceSchema>;
export type SnapshotDetail = z.infer<typeof snapshotDetailSchema>;
export type WorldModelDetail = z.infer<typeof worldModelDetailSchema>;
export type WorldModelEvidenceSelection = z.infer<typeof worldModelEvidenceSelectionSchema>;
export type WorldModelCreateRequest = z.infer<typeof worldModelCreateRequestSchema>;
export type EvidenceWorldGraphNode = z.infer<typeof evidenceWorldGraphNodeSchema>;
export type EvidenceWorldGraph = z.infer<typeof evidenceWorldGraphSchema>;
export type SemanticWorldGraphNode = z.infer<typeof semanticWorldGraphNodeSchema>;
export type SemanticWorldGraphEdge = z.infer<typeof semanticWorldGraphEdgeSchema>;
export type SemanticWorldGraph = z.infer<typeof semanticWorldGraphSchema>;
export type SemanticWorldGraphsResponse = z.infer<typeof semanticWorldGraphsResponseSchema>;
export type SemanticWorldGraphSliceDirection = z.infer<typeof semanticWorldGraphSliceDirectionSchema>;
export type SemanticWorldGraphSlice = z.infer<typeof semanticWorldGraphSliceSchema>;
export type SemanticWorldGraphEvidenceTimeline = z.infer<typeof semanticWorldGraphEvidenceTimelineSchema>;

export function buildWorldModelCreateRequest(
  title: string,
  selectedArticles: readonly MediaArticle[],
): WorldModelCreateRequest {
  return worldModelCreateRequestSchema.parse({
    title,
    evidence: selectedArticles.map((article) => ({
      article_id: article.id,
      evidence_revision_sha256: article.evidence_revision_sha256,
    })),
    verification: "human_confirmed",
  });
}

export function createWorldModelDetailEndpoint(worldModelId: string): string {
  return `${worldModelsEndpoint}/${encodeURIComponent(worldModelId)}`;
}

export function fetchWorldModels(signal: AbortSignal): Promise<WorldModelsResponse> {
  return getJson(worldModelsEndpoint, worldModelsResponseSchema, signal);
}

export function fetchWorldModelDetail(
  worldModelId: string,
  signal: AbortSignal,
): Promise<WorldModelDetail> {
  return getJson(
    createWorldModelDetailEndpoint(worldModelId),
    worldModelDetailSchema,
    signal,
  );
}

export function fetchEvidenceWorldGraph(
  worldModelId: string,
  snapshotId: string,
  signal: AbortSignal,
): Promise<EvidenceWorldGraph> {
  return getJson(
    `${createWorldModelDetailEndpoint(worldModelId)}/snapshots/${encodeURIComponent(snapshotId)}/evidence-graph`,
    evidenceWorldGraphSchema,
    signal,
  );
}

function semanticWorldGraphsEndpoint(worldModelId: string, snapshotId: string): string {
  return `${createWorldModelDetailEndpoint(worldModelId)}/snapshots/${encodeURIComponent(snapshotId)}/semantic-graphs`;
}

export function fetchSemanticWorldGraphs(
  worldModelId: string,
  snapshotId: string,
  signal: AbortSignal,
): Promise<SemanticWorldGraphsResponse> {
  return getJson(
    semanticWorldGraphsEndpoint(worldModelId, snapshotId),
    semanticWorldGraphsResponseSchema,
    signal,
  );
}

export function enqueueSemanticWorldGraph(
  worldModelId: string,
  snapshotId: string,
  signal: AbortSignal,
): Promise<SemanticWorldGraph> {
  return postJson(
    semanticWorldGraphsEndpoint(worldModelId, snapshotId),
    {},
    semanticWorldGraphSchema,
    signal,
  );
}

export function fetchSemanticWorldGraphSlice(
  graphId: string,
  rootNodeId: string,
  direction: SemanticWorldGraphSliceDirection,
  hops: number,
  maxNodes: number,
  signal: AbortSignal,
): Promise<SemanticWorldGraphSlice> {
  const query = new URLSearchParams({
    root_node_id: rootNodeId,
    direction,
    hops: String(hops),
    max_nodes: String(maxNodes),
  });
  return getJson(
    `/api/v2/world-graphs/${encodeURIComponent(graphId)}/slice?${query.toString()}`,
    semanticWorldGraphSliceSchema,
    signal,
  );
}

export function fetchSemanticWorldGraphEvidenceTimeline(
  graphId: string,
  signal: AbortSignal,
): Promise<SemanticWorldGraphEvidenceTimeline> {
  return getJson(
    `/api/v2/world-graphs/${encodeURIComponent(graphId)}/evidence-timeline`,
    semanticWorldGraphEvidenceTimelineSchema,
    signal,
  );
}

export function createWorldModel(
  request: WorldModelCreateRequest,
  signal: AbortSignal,
): Promise<WorldModelDetail> {
  const validatedRequest = worldModelCreateRequestSchema.parse(request);

  return postJson(worldModelsEndpoint, validatedRequest, worldModelDetailSchema, signal);
}
