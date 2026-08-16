import { z } from "zod";

import { getJson, postJson } from "./apiClient";
import { sha256DigestSchema, type MediaArticle } from "./mediaContracts";
import type { PolicyDocumentSummary } from "./policyEvidenceContracts";
import {
  cohortCreateRequestSchema,
  cohortDatasetSchema,
  cohortDetailSchema,
  personaAttributeSchema,
  personaSummarySchema,
  type CohortCreateRequest,
} from "./populationContracts";

const worldModelsEndpoint = "/api/v2/world-models";
const identifierSchema = z.string().uuid();
const isoTimestampSchema = z.string().datetime({ offset: true });
const isoDateSchema = z.string().regex(/^\d{4}-\d{2}-\d{2}$/u);
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
    policy_evidence_count: z.number().int().min(0).max(50),
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

export const snapshotPolicyEvidenceSchema = z
  .object({
    policy_version_id: identifierSchema,
    authority_name: nonEmptyTextSchema.max(300),
    jurisdiction_code: z.string().regex(/^[A-Z0-9][A-Z0-9-]{1,15}$/u),
    homepage_url: httpUrlSchema,
    canonical_identifier: nonEmptyTextSchema.max(256),
    source_sha256: sha256DigestSchema,
    document_sha256: sha256DigestSchema,
    version: z.number().int().min(1).max(100),
    title: nonEmptyTextSchema.max(500),
    original_url: httpUrlSchema,
    language: z.string().regex(/^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/u),
    publication_date: isoDateSchema,
    effective_from: isoDateSchema.nullable(),
    effective_until: isoDateSchema.nullable(),
    captured_at: isoTimestampSchema,
    content_sha256: sha256DigestSchema,
    version_sha256: sha256DigestSchema,
  })
  .strict()
  .superRefine((item, context) => {
    if (item.effective_from !== null && item.effective_until !== null
      && item.effective_until <= item.effective_from) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["effective_until"],
        message: "Policy effective_until must follow effective_from",
      });
    }
  });

export const snapshotDetailSchema = z
  .object({
    id: identifierSchema,
    world_model_id: identifierSchema,
    version: z.number().int().positive(),
    verification: z.literal("human_confirmed"),
    snapshot_sha256: sha256DigestSchema,
    created_at: isoTimestampSchema,
    evidence: z.array(snapshotEvidenceSchema).min(1).max(50),
    policy_evidence: z.array(snapshotPolicyEvidenceSchema).max(50),
  })
  .strict()
  .refine(
    (snapshot) => snapshot.evidence.length + snapshot.policy_evidence.length <= 50,
    { message: "Snapshot cannot contain more than 50 total evidence items" },
  );

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
      || latestSummary.policy_evidence_count !== worldModel.latest_snapshot.policy_evidence.length
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

export const worldModelPolicyEvidenceSelectionSchema = z
  .object({
    policy_version_id: identifierSchema,
    version_sha256: sha256DigestSchema,
  })
  .strict();

const worldModelEvidenceArraySchema = z.array(worldModelEvidenceSelectionSchema).min(1).max(50);
const worldModelPolicyEvidenceArraySchema = z
  .array(worldModelPolicyEvidenceSelectionSchema)
  .max(50);

function hasDuplicateEvidenceArticleIds(
  evidence: readonly WorldModelEvidenceSelection[],
): boolean {
  const articleIds = evidence.map((selection) => selection.article_id);

  return new Set(articleIds).size !== articleIds.length;
}

function hasDuplicatePolicyVersionIds(
  evidence: readonly WorldModelPolicyEvidenceSelection[],
): boolean {
  const versionIds = evidence.map((selection) => selection.policy_version_id);
  return new Set(versionIds).size !== versionIds.length;
}

function validateCreateEvidence(
  request: {
    readonly evidence: readonly WorldModelEvidenceSelection[];
    readonly policy_evidence: readonly WorldModelPolicyEvidenceSelection[];
  },
  context: z.RefinementCtx,
): void {
  if (hasDuplicateEvidenceArticleIds(request.evidence)) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["evidence"],
      message: "evidence article_id values must not contain duplicates",
    });
  }
  if (hasDuplicatePolicyVersionIds(request.policy_evidence)) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["policy_evidence"],
      message: "policy_evidence policy_version_id values must not contain duplicates",
    });
  }
  if (request.evidence.length + request.policy_evidence.length > 50) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["policy_evidence"],
      message: "snapshot cannot contain more than 50 total evidence items",
    });
  }
}

export const worldModelCreateRequestSchema = z
  .object({
    title: worldModelTitleSchema,
    evidence: worldModelEvidenceArraySchema,
    policy_evidence: worldModelPolicyEvidenceArraySchema,
    verification: z.literal("human_confirmed"),
  })
  .strict()
  .superRefine(validateCreateEvidence);

export const worldSnapshotCreateRequestSchema = z
  .object({
    evidence: worldModelEvidenceArraySchema,
    policy_evidence: worldModelPolicyEvidenceArraySchema,
    verification: z.literal("human_confirmed"),
  })
  .strict()
  .superRefine(validateCreateEvidence);

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

const semanticWorldGraphEdgeSignatureSchema = z.object({
  source_entity_type: semanticWorldGraphEntityTypeSchema,
  source_name: nonEmptyTextSchema.max(200),
  relation_type: z.string().regex(/^[a-z][a-z0-9_]{0,63}$/u),
  target_entity_type: semanticWorldGraphEntityTypeSchema,
  target_name: nonEmptyTextSchema.max(200),
  fact: nonEmptyTextSchema.max(500),
}).strict();

const semanticWorldGraphEdgeObservationSchema = z.object({
  position: z.number().int().min(0).max(49),
  graph_id: identifierSchema,
  graph_sha256: sha256DigestSchema,
  graph_created_at: isoTimestampSchema,
  graph_completed_at: isoTimestampSchema,
  snapshot_id: identifierSchema,
  snapshot_sha256: sha256DigestSchema,
  snapshot_version: z.number().int().positive(),
  edge_id: identifierSchema,
  evidence_article_ids: z.array(identifierSchema).min(1).max(20),
  evidence_published_from: isoTimestampSchema,
  evidence_published_through: isoTimestampSchema,
}).strict().superRefine((item, context) => {
  if (
    Date.parse(item.graph_completed_at) < Date.parse(item.graph_created_at)
    || Date.parse(item.evidence_published_through) < Date.parse(item.evidence_published_from)
    || new Set(item.evidence_article_ids).size !== item.evidence_article_ids.length
  ) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: "Semantic graph edge observation is inconsistent",
    });
  }
});

export const semanticWorldGraphEdgeHistorySchema = z.object({
  graph_id: identifierSchema,
  graph_sha256: sha256DigestSchema,
  edge_id: identifierSchema,
  observation_semantics: z.literal("cross_snapshot_exact_signature_not_fact_validity"),
  signature: semanticWorldGraphEdgeSignatureSchema,
  inspected_graph_count: z.number().int().min(1).max(12),
  total_succeeded_graph_count: z.number().int().min(1),
  truncated: z.boolean(),
  items: z.array(semanticWorldGraphEdgeObservationSchema).min(1).max(50),
  limitations: z.array(nonEmptyTextSchema).length(3),
}).strict().superRefine((history, context) => {
  const positionsAreContiguous = history.items.every((item, index) => item.position === index);
  const occurrenceIds = history.items.map((item) => `${item.graph_id}:${item.edge_id}`);
  const currentOccurrences = history.items.filter(
    (item) => item.graph_id === history.graph_id && item.edge_id === history.edge_id,
  );
  const ordered = history.items.every((item, index) => {
    const previous = history.items[index - 1];
    if (previous === undefined) return true;
    if (item.snapshot_version !== previous.snapshot_version) {
      return item.snapshot_version > previous.snapshot_version;
    }
    return Date.parse(item.graph_created_at) >= Date.parse(previous.graph_created_at);
  });
  if (
    !positionsAreContiguous
    || new Set(occurrenceIds).size !== occurrenceIds.length
    || currentOccurrences.length !== 1
    || currentOccurrences[0]?.graph_sha256 !== history.graph_sha256
    || !ordered
    || history.total_succeeded_graph_count < history.inspected_graph_count
    || history.truncated !== (history.total_succeeded_graph_count > history.inspected_graph_count)
  ) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: "Semantic graph edge history is inconsistent",
    });
  }
});

const semanticWorldGraphPersonaMatchSchema = z.object({
  position: z.number().int().min(0).max(19),
  score: z.number().int().min(1).max(20),
  matched_terms: z.array(nonEmptyTextSchema).min(1).max(20),
  matched_attributes: z.array(personaAttributeSchema).min(1).max(20),
  persona: personaSummarySchema,
}).strict().superRefine((match, context) => {
  const terms = [...match.matched_terms].sort();
  const termSet = new Set(match.matched_terms);
  const attributeNames = new Set(match.matched_attributes.map((attribute) => attribute.name));
  const personaAttributes = new Set(
    match.persona.attributes.map((attribute) => `${attribute.name}\u0000${attribute.value}`),
  );
  if (
    match.score !== match.matched_terms.length
    || termSet.size !== match.matched_terms.length
    || match.matched_terms.some((term, index) => term !== terms[index])
    || attributeNames.size !== match.matched_attributes.length
    || match.matched_attributes.some(
      (attribute) => !personaAttributes.has(`${attribute.name}\u0000${attribute.value}`),
    )
  ) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: "Semantic world graph Persona match is inconsistent",
    });
  }
});

export const semanticWorldGraphPersonaMatchesSchema = z.object({
  graph_id: identifierSchema,
  graph_sha256: sha256DigestSchema,
  node_id: identifierSchema,
  dataset: cohortDatasetSchema,
  match_semantics: z.literal("exact_token_overlap_non_low_information_attributes"),
  query_terms: z.array(nonEmptyTextSchema).min(1).max(20),
  inspected_persona_count: z.number().int().min(0).max(200),
  dataset_persona_count: z.number().int().min(1).max(1_000_000),
  scan_truncated: z.boolean(),
  total_match_count_in_scan: z.number().int().min(0).max(200),
  matches: z.array(semanticWorldGraphPersonaMatchSchema).max(20),
  limitations: z.array(nonEmptyTextSchema).length(3),
}).strict().superRefine((response, context) => {
  const positionsAreContiguous = response.matches.every(
    (match, index) => match.position === index,
  );
  const personaIds = response.matches.map((match) => match.persona.id);
  const terms = [...response.query_terms].sort();
  const termSet = new Set(response.query_terms);
  const matchesAreConsistent = response.matches.every(
    (match) => match.persona.dataset_id === response.dataset.id
      && match.matched_terms.every((term) => termSet.has(term)),
  );
  if (
    !positionsAreContiguous
    || new Set(personaIds).size !== personaIds.length
    || termSet.size !== response.query_terms.length
    || response.query_terms.some((term, index) => term !== terms[index])
    || !matchesAreConsistent
    || response.inspected_persona_count > response.dataset_persona_count
    || response.total_match_count_in_scan > response.inspected_persona_count
    || response.total_match_count_in_scan < response.matches.length
    || response.scan_truncated
      !== (response.dataset_persona_count > response.inspected_persona_count)
  ) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: "Semantic world graph Persona match response is inconsistent",
    });
  }
});

export const graphPersonaCohortCreateRequestSchema = cohortCreateRequestSchema.superRefine(
  (request, context) => {
    if (request.persona_ids.length > 8) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["persona_ids"],
        message: "graph-guided cohort selection cannot exceed 8 Personas",
      });
    }
  },
);

export const graphPersonaCohortOriginSchema = z.object({
  id: identifierSchema,
  graph_id: identifierSchema,
  graph_sha256: sha256DigestSchema,
  node_id: identifierSchema,
  dataset: cohortDatasetSchema,
  cohort_id: identifierSchema,
  cohort_sha256: sha256DigestSchema,
  match_semantics: z.literal("exact_token_overlap_non_low_information_attributes"),
  matcher_version: z.literal("1.0.0"),
  selected_persona_ids: z.array(identifierSchema).min(1).max(8),
  origin_sha256: sha256DigestSchema,
  created_at: isoTimestampSchema,
}).strict().superRefine((origin, context) => {
  if (new Set(origin.selected_persona_ids).size !== origin.selected_persona_ids.length) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      path: ["selected_persona_ids"],
      message: "graph Persona origin selection must be unique",
    });
  }
});

export const graphPersonaCohortCreationSchema = z.object({
  origin: graphPersonaCohortOriginSchema,
  cohort: cohortDetailSchema,
}).strict().superRefine((result, context) => {
  const memberIds = result.cohort.members.map((member) => member.persona.id);
  if (
    result.origin.cohort_id !== result.cohort.id
    || result.origin.cohort_sha256 !== result.cohort.cohort_sha256
    || result.origin.dataset.id !== result.cohort.dataset.id
    || result.origin.dataset.dataset_sha256 !== result.cohort.dataset.dataset_sha256
    || result.origin.selected_persona_ids.length !== memberIds.length
    || result.origin.selected_persona_ids.some((personaId, index) => personaId !== memberIds[index])
  ) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: "graph Persona cohort origin does not match the returned cohort",
    });
  }
});

export const graphPersonaCohortOriginsResponseSchema = z.object({
  items: z.array(graphPersonaCohortOriginSchema),
  page: z.number().int().min(1),
  page_size: z.number().int().min(1).max(100),
  total: z.number().int().min(0),
}).strict().superRefine((response, context) => {
  const cohortIds = new Set(response.items.map((item) => item.cohort_id));
  const orderingIsValid = response.items.every((item, index) => {
    const previous = response.items[index - 1];
    if (previous === undefined) return true;
    const currentTime = Date.parse(item.created_at);
    const previousTime = Date.parse(previous.created_at);
    return previousTime > currentTime
      || (previousTime === currentTime && previous.id.localeCompare(item.id) <= 0);
  });
  if (
    response.items.length > response.page_size
    || response.items.length > response.total
    || cohortIds.size > 1
    || !orderingIsValid
  ) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: "graph Persona cohort origin page is inconsistent",
    });
  }
});

const semanticWorldGraphSearchMatchFieldSchema = z.enum([
  "name",
  "summary",
  "entity_type",
  "relation_type",
  "fact",
  "evidence_quote",
]);
const semanticWorldGraphNodeSearchResultSchema = z.object({
  kind: z.literal("node"),
  rank: z.number().int().min(0).max(49),
  matched_fields: z.array(semanticWorldGraphSearchMatchFieldSchema).min(1).max(4),
  node: semanticWorldGraphNodeSchema,
}).strict();
const semanticWorldGraphEdgeSearchResultSchema = z.object({
  kind: z.literal("edge"),
  rank: z.number().int().min(0).max(49),
  matched_fields: z.array(semanticWorldGraphSearchMatchFieldSchema).min(1).max(3),
  edge: semanticWorldGraphEdgeSchema,
}).strict();
export const semanticWorldGraphSearchResponseSchema = z.object({
  graph_id: identifierSchema,
  graph_sha256: sha256DigestSchema,
  query: nonEmptyTextSchema.min(2).max(100).regex(/^[^\r\n]+$/u),
  search_semantics: z.literal("casefolded_lexical_substring"),
  total_match_count: z.number().int().min(0).max(2500),
  truncated: z.boolean(),
  results: z.array(z.discriminatedUnion("kind", [
    semanticWorldGraphNodeSearchResultSchema,
    semanticWorldGraphEdgeSearchResultSchema,
  ])).max(50),
  limitations: z.array(nonEmptyTextSchema).min(2).max(3),
}).strict().superRefine((response, context) => {
  const ranksAreContiguous = response.results.every((result, index) => result.rank === index);
  const identities = response.results.map((result) => (
    `${result.kind}:${result.kind === "node" ? result.node.id : result.edge.id}`
  ));
  if (
    !ranksAreContiguous
    || new Set(identities).size !== identities.length
    || response.total_match_count < response.results.length
    || response.truncated !== (response.total_match_count > response.results.length)
  ) {
    context.addIssue({
      code: z.ZodIssueCode.custom,
      message: "Semantic world graph search response is inconsistent",
    });
  }
});

export type SnapshotSummary = z.infer<typeof snapshotSummarySchema>;
export type WorldModelSummary = z.infer<typeof worldModelSummarySchema>;
export type WorldModelsResponse = z.infer<typeof worldModelsResponseSchema>;
export type SnapshotEvidence = z.infer<typeof snapshotEvidenceSchema>;
export type SnapshotDetail = z.infer<typeof snapshotDetailSchema>;
export type SnapshotPolicyEvidence = z.infer<typeof snapshotPolicyEvidenceSchema>;
export type WorldModelDetail = z.infer<typeof worldModelDetailSchema>;
export type WorldModelEvidenceSelection = z.infer<typeof worldModelEvidenceSelectionSchema>;
export type WorldModelPolicyEvidenceSelection = z.infer<
  typeof worldModelPolicyEvidenceSelectionSchema
>;
export type WorldModelCreateRequest = z.infer<typeof worldModelCreateRequestSchema>;
export type WorldSnapshotCreateRequest = z.infer<typeof worldSnapshotCreateRequestSchema>;
export type EvidenceWorldGraphNode = z.infer<typeof evidenceWorldGraphNodeSchema>;
export type EvidenceWorldGraph = z.infer<typeof evidenceWorldGraphSchema>;
export type SemanticWorldGraphNode = z.infer<typeof semanticWorldGraphNodeSchema>;
export type SemanticWorldGraphEdge = z.infer<typeof semanticWorldGraphEdgeSchema>;
export type SemanticWorldGraph = z.infer<typeof semanticWorldGraphSchema>;
export type SemanticWorldGraphsResponse = z.infer<typeof semanticWorldGraphsResponseSchema>;
export type SemanticWorldGraphSliceDirection = z.infer<typeof semanticWorldGraphSliceDirectionSchema>;
export type SemanticWorldGraphSlice = z.infer<typeof semanticWorldGraphSliceSchema>;
export type SemanticWorldGraphEvidenceTimeline = z.infer<typeof semanticWorldGraphEvidenceTimelineSchema>;
export type SemanticWorldGraphEdgeHistory = z.infer<typeof semanticWorldGraphEdgeHistorySchema>;
export type SemanticWorldGraphPersonaMatches = z.infer<
  typeof semanticWorldGraphPersonaMatchesSchema
>;
export type GraphPersonaCohortCreation = z.infer<typeof graphPersonaCohortCreationSchema>;
export type GraphPersonaCohortOriginsResponse = z.infer<
  typeof graphPersonaCohortOriginsResponseSchema
>;
export type SemanticWorldGraphSearchResponse = z.infer<typeof semanticWorldGraphSearchResponseSchema>;

export function buildWorldModelCreateRequest(
  title: string,
  selectedArticles: readonly MediaArticle[],
  selectedPolicies: readonly PolicyDocumentSummary[],
): WorldModelCreateRequest {
  return worldModelCreateRequestSchema.parse({
    title,
    evidence: selectedArticles.map((article) => ({
      article_id: article.id,
      evidence_revision_sha256: article.evidence_revision_sha256,
    })),
    policy_evidence: selectedPolicies.map((document) => ({
      policy_version_id: document.latest_version.id,
      version_sha256: document.latest_version.version_sha256,
    })),
    verification: "human_confirmed",
  });
}

export function buildWorldSnapshotCreateRequest(
  selectedArticles: readonly MediaArticle[],
  selectedPolicies: readonly PolicyDocumentSummary[],
): WorldSnapshotCreateRequest {
  return worldSnapshotCreateRequestSchema.parse({
    evidence: selectedArticles.map((article) => ({
      article_id: article.id,
      evidence_revision_sha256: article.evidence_revision_sha256,
    })),
    policy_evidence: selectedPolicies.map((document) => ({
      policy_version_id: document.latest_version.id,
      version_sha256: document.latest_version.version_sha256,
    })),
    verification: "human_confirmed",
  });
}

export function createWorldModelDetailEndpoint(worldModelId: string): string {
  return `${worldModelsEndpoint}/${encodeURIComponent(worldModelId)}`;
}

export function createWorldSnapshotEndpoint(
  worldModelId: string,
  snapshotId: string | null,
): string {
  const snapshotsEndpoint = `${createWorldModelDetailEndpoint(worldModelId)}/snapshots`;

  return snapshotId === null
    ? snapshotsEndpoint
    : `${snapshotsEndpoint}/${encodeURIComponent(snapshotId)}`;
}

function createSnapshotResponseSchema(
  worldModelId: string,
  snapshotId: string | null,
): z.ZodEffects<typeof snapshotDetailSchema> {
  return snapshotDetailSchema.superRefine((snapshot, context) => {
    if (snapshot.world_model_id !== worldModelId) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["world_model_id"],
        message: "snapshot must belong to the requested world model",
      });
    }

    if (snapshotId !== null && snapshot.id !== snapshotId) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        path: ["id"],
        message: "snapshot must match the requested snapshot identifier",
      });
    }
  });
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

export function fetchWorldSnapshot(
  worldModelId: string,
  snapshotId: string,
  signal: AbortSignal,
): Promise<SnapshotDetail> {
  return getJson(
    createWorldSnapshotEndpoint(worldModelId, snapshotId),
    createSnapshotResponseSchema(worldModelId, snapshotId),
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

export function fetchSemanticWorldGraphEdgeHistory(
  graphId: string,
  edgeId: string,
  signal: AbortSignal,
): Promise<SemanticWorldGraphEdgeHistory> {
  return getJson(
    `/api/v2/world-graphs/${encodeURIComponent(graphId)}/edges/${encodeURIComponent(edgeId)}/history`,
    semanticWorldGraphEdgeHistorySchema,
    signal,
  ).then((history) => {
    if (history.graph_id !== graphId || history.edge_id !== edgeId) {
      throw new Error("关系观察历史响应与请求的图谱或关系不一致。");
    }
    return history;
  });
}

export function fetchSemanticWorldGraphPersonaMatches(
  graphId: string,
  nodeId: string,
  datasetId: string,
  limit: number,
  signal: AbortSignal,
): Promise<SemanticWorldGraphPersonaMatches> {
  const validatedGraphId = identifierSchema.parse(graphId);
  const validatedNodeId = identifierSchema.parse(nodeId);
  const validatedDatasetId = identifierSchema.parse(datasetId);
  if (!Number.isInteger(limit) || limit < 1 || limit > 20) {
    throw new Error("Persona 候选 limit 必须是 1–20 的整数。");
  }
  const parameters = new URLSearchParams({
    dataset_id: validatedDatasetId,
    limit: String(limit),
  });
  return getJson(
    `/api/v2/world-graphs/${encodeURIComponent(validatedGraphId)}/nodes/${encodeURIComponent(validatedNodeId)}/persona-matches?${parameters.toString()}`,
    semanticWorldGraphPersonaMatchesSchema,
    signal,
  ).then((response) => {
    if (
      response.graph_id !== validatedGraphId
      || response.node_id !== validatedNodeId
      || response.dataset.id !== validatedDatasetId
    ) {
      throw new Error("Persona 候选响应与请求的图谱、节点或数据集不一致。");
    }
    return response;
  });
}

export function createGraphPersonaCohort(
  graphId: string,
  nodeId: string,
  request: CohortCreateRequest,
  signal: AbortSignal,
): Promise<GraphPersonaCohortCreation> {
  const validatedGraphId = identifierSchema.parse(graphId);
  const validatedNodeId = identifierSchema.parse(nodeId);
  const validatedRequest = graphPersonaCohortCreateRequestSchema.parse(request);
  return postJson(
    `/api/v2/world-graphs/${encodeURIComponent(validatedGraphId)}/nodes/${encodeURIComponent(validatedNodeId)}/cohorts`,
    validatedRequest,
    graphPersonaCohortCreationSchema,
    signal,
  ).then((result) => {
    if (result.origin.graph_id !== validatedGraphId || result.origin.node_id !== validatedNodeId) {
      throw new Error("图谱 Persona Cohort 来源与请求的图谱或节点不一致。");
    }
    return result;
  });
}

export function fetchGraphPersonaCohortOrigins(
  cohortId: string,
  page: number,
  pageSize: number,
  signal: AbortSignal,
): Promise<GraphPersonaCohortOriginsResponse> {
  const validatedCohortId = identifierSchema.parse(cohortId);
  if (!Number.isInteger(page) || page < 1) {
    throw new Error("图谱 Persona 来源 page 必须是正整数。");
  }
  if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > 100) {
    throw new Error("图谱 Persona 来源 page_size 必须是 1–100 的整数。");
  }
  const parameters = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  return getJson(
    `/api/v2/populations/cohorts/${encodeURIComponent(validatedCohortId)}/graph-origins?${parameters.toString()}`,
    graphPersonaCohortOriginsResponseSchema,
    signal,
  ).then((response) => {
    if (response.items.some((item) => item.cohort_id !== validatedCohortId)) {
      throw new Error("图谱 Persona 来源响应包含其他 Cohort 的记录。");
    }
    return response;
  });
}

export function fetchSemanticWorldGraphSearch(
  graphId: string,
  queryValue: string,
  limit: number,
  signal: AbortSignal,
): Promise<SemanticWorldGraphSearchResponse> {
  const query = queryValue.trim();
  if (query.length < 2 || query.length > 100 || /[\r\n]/u.test(query)) {
    throw new Error("图谱检索词必须是 2–100 个字符的单行文本。");
  }
  if (!Number.isInteger(limit) || limit < 1 || limit > 50) {
    throw new Error("图谱检索 limit 必须是 1–50 的整数。");
  }
  const parameters = new URLSearchParams({ q: query, limit: String(limit) });
  return getJson(
    `/api/v2/world-graphs/${encodeURIComponent(graphId)}/search?${parameters.toString()}`,
    semanticWorldGraphSearchResponseSchema,
    signal,
  ).then((response) => {
    if (response.graph_id !== graphId || response.query !== query) {
      throw new Error("图谱检索响应与请求的图谱或检索词不一致。");
    }
    return response;
  });
}

export function createWorldModel(
  request: WorldModelCreateRequest,
  signal: AbortSignal,
): Promise<WorldModelDetail> {
  const validatedRequest = worldModelCreateRequestSchema.parse(request);

  return postJson(worldModelsEndpoint, validatedRequest, worldModelDetailSchema, signal);
}

export function appendWorldSnapshot(
  worldModelId: string,
  request: WorldSnapshotCreateRequest,
  signal: AbortSignal,
): Promise<SnapshotDetail> {
  const validatedRequest = worldSnapshotCreateRequestSchema.parse(request);

  return postJson(
    createWorldSnapshotEndpoint(worldModelId, null),
    validatedRequest,
    createSnapshotResponseSchema(worldModelId, null),
    signal,
  );
}
