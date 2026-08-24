import { z } from "zod";

import { getJson, postJson } from "./apiClient";
import { sha256DigestSchema } from "./mediaContracts";

const identifierSchema = z.string().uuid();
const timestampSchema = z.string().datetime({ offset: true });

export const agentInteractionCitationSchema = z.object({
  position: z.number().int().min(0).max(19),
  source_kind: z.literal("simulation_run"),
  target_id: identifierSchema,
  source_label: z.string().trim().min(1).max(500),
  quote: z.string().min(1).max(500),
  start_offset: z.number().int().min(0),
  end_offset: z.number().int().min(1),
}).strict().refine(
  (citation) => citation.end_offset - citation.start_offset === citation.quote.length,
  { message: "Agent Interaction citation offsets must span the exact quote" },
);

export const agentInteractionSchema = z.object({
  id: identifierSchema,
  research_project_id: identifierSchema,
  research_simulation_run_id: identifierSchema,
  report_agent_run_id: identifierSchema,
  report_agent_run_sha256: sha256DigestSchema,
  report_agent_draft_id: identifierSchema,
  report_agent_draft_sha256: sha256DigestSchema,
  source_sha256: sha256DigestSchema,
  question: z.string().trim().min(2).max(1000),
  interaction_sha256: sha256DigestSchema,
  model_name: z.string().trim().min(1).max(200),
  semantic_config_sha256: sha256DigestSchema,
  prompt_schema_version: z.enum([
    "sandowl-agent-interaction/v1",
    "sandowl-agent-interaction/v2",
  ]),
  parent_interaction_id: identifierSchema.nullable(),
  parent_interaction_sha256: sha256DigestSchema.nullable(),
  parent_answer_sha256: sha256DigestSchema.nullable(),
  conversation_depth: z.number().int().min(0).max(4),
  status: z.enum(["queued", "running", "succeeded", "failed"]),
  created_at: timestampSchema,
  started_at: timestampSchema.nullable(),
  completed_at: timestampSchema.nullable(),
  answer_markdown: z.string().trim().min(1).max(1200).nullable(),
  citations: z.array(agentInteractionCitationSchema).max(20),
  answer_sha256: sha256DigestSchema.nullable(),
  error_code: z.string().min(1).max(128).nullable(),
  error_message: z.string().min(1).max(500).nullable(),
}).strict().superRefine((item, context) => {
  const root = item.parent_interaction_id === null;
  if (root !== (item.conversation_depth === 0)
    || root !== (item.parent_interaction_sha256 === null)
    || root !== (item.parent_answer_sha256 === null)) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "Agent Interaction lineage is invalid" });
  }
  const terminal = item.status === "succeeded" || item.status === "failed";
  const timestampsValid = item.status === "queued"
    ? item.started_at === null && item.completed_at === null
    : item.started_at !== null && (terminal ? item.completed_at !== null : item.completed_at === null);
  const outputValid = item.status === "succeeded"
    ? item.answer_markdown !== null && item.citations.length > 0 && item.answer_sha256 !== null
      && item.error_code === null && item.error_message === null
    : item.answer_markdown === null && item.citations.length === 0 && item.answer_sha256 === null
      && (item.status === "failed"
        ? item.error_code !== null && item.error_message !== null
        : item.error_code === null && item.error_message === null);
  if (!timestampsValid || !outputValid) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "Agent Interaction lifecycle is invalid" });
  }
  if (!item.citations.every((citation, position) => citation.position === position)) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "Agent Interaction citations are not contiguous" });
  }
});

export const agentInteractionsResponseSchema = z.object({
  items: z.array(agentInteractionSchema),
  total: z.number().int().min(0),
}).strict().refine((response) => response.total === response.items.length, {
  message: "Agent Interaction total must match items",
});

export type AgentInteraction = z.infer<typeof agentInteractionSchema>;
export type AgentInteractionsResponse = z.infer<typeof agentInteractionsResponseSchema>;

export function fetchAgentInteractions(
  draftId: string,
  signal: AbortSignal,
): Promise<AgentInteractionsResponse> {
  return getJson(
    `/api/v2/report-agent/drafts/${encodeURIComponent(identifierSchema.parse(draftId))}/interactions`,
    agentInteractionsResponseSchema,
    signal,
  );
}

export function createAgentInteraction(
  draftId: string,
  question: string,
  parentInteractionId: string | null,
  signal: AbortSignal,
): Promise<AgentInteraction> {
  return postJson(
    `/api/v2/report-agent/drafts/${encodeURIComponent(identifierSchema.parse(draftId))}/interactions`,
    { question, parent_interaction_id: parentInteractionId },
    agentInteractionSchema,
    signal,
  );
}

export function fetchAgentInteraction(
  interactionId: string,
  signal: AbortSignal,
): Promise<AgentInteraction> {
  return getJson(
    `/api/v2/agent-interactions/${encodeURIComponent(identifierSchema.parse(interactionId))}`,
    agentInteractionSchema,
    signal,
  );
}
