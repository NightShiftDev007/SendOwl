import { z } from "zod";

import { getJson, postJson } from "./apiClient";
import { sha256DigestSchema } from "./mediaContracts";

const uuidSchema = z.string().uuid();
const timestampSchema = z.string().datetime({ offset: true });

export const personaInterviewPersonaSchema = z.object({
  id: uuidSchema,
  position: z.number().int().min(0).max(99),
  persona_id: z.string().regex(/^[A-Za-z0-9][A-Za-z0-9_.:-]*$/).max(128),
  display_name: z.string().trim().min(1).max(200).refine((value) => !/[\r\n]/u.test(value)),
  profile_sha256: sha256DigestSchema,
}).strict();

export const personaInterviewSchema = z.object({
  id: uuidSchema,
  report_id: uuidSchema,
  report_sha256: sha256DigestSchema,
  cohort_id: uuidSchema,
  cohort_sha256: sha256DigestSchema,
  persona: personaInterviewPersonaSchema,
  question: z.string().trim().min(2).max(1000),
  interview_sha256: sha256DigestSchema,
  model_name: z.string().trim().min(1).max(200),
  semantic_config_sha256: sha256DigestSchema,
  prompt_schema_version: z.literal("persona-report-interview/v1"),
  status: z.enum(["queued", "running", "succeeded", "failed"]),
  created_at: timestampSchema,
  started_at: timestampSchema.nullable(),
  completed_at: timestampSchema.nullable(),
  answer_markdown: z.string().min(1).max(2000).nullable(),
  cited_section_positions: z.array(z.number().int().min(0).max(3)).max(4),
  answer_sha256: sha256DigestSchema.nullable(),
  error_code: z.string().min(1).max(128).nullable(),
  error_message: z.string().min(1).max(500).nullable(),
}).strict().superRefine((value, context) => {
  const positions = value.cited_section_positions;
  const sortedUniquePositions = [...new Set(positions)].sort((left, right) => left - right);
  if (positions.some((position, index) => position !== sortedUniquePositions[index])) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["cited_section_positions"], message: "section positions must be sorted and unique" });
  }
  const waiting = value.answer_markdown === null && positions.length === 0
    && value.answer_sha256 === null && value.error_code === null && value.error_message === null;
  const succeeded = value.answer_markdown !== null && positions.length > 0
    && value.answer_sha256 !== null && value.error_code === null && value.error_message === null;
  const failed = value.answer_markdown === null && positions.length === 0
    && value.answer_sha256 === null && value.error_code !== null && value.error_message !== null;
  const valid = value.status === "queued"
    ? value.started_at === null && value.completed_at === null && waiting
    : value.status === "running"
      ? value.started_at !== null && value.completed_at === null && waiting
      : value.status === "succeeded"
        ? value.started_at !== null && value.completed_at !== null && succeeded
        : value.started_at !== null && value.completed_at !== null && failed;
  if (!valid) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "Persona interview lifecycle is invalid" });
  }
});

export const personaInterviewsResponseSchema = z.object({
  items: z.array(personaInterviewSchema),
  total: z.number().int().nonnegative(),
}).strict();

export const personaInterviewSessionSchema = z.object({
  id: uuidSchema,
  report_id: uuidSchema,
  report_sha256: sha256DigestSchema,
  cohort_id: uuidSchema,
  cohort_sha256: sha256DigestSchema,
  question: z.string().trim().min(2).max(1000),
  persona_count: z.number().int().min(2).max(8),
  session_sha256: sha256DigestSchema,
  model_name: z.string().trim().min(1).max(200),
  semantic_config_sha256: sha256DigestSchema,
  prompt_schema_version: z.literal("persona-report-interview-session/v1"),
  status: z.enum(["queued", "running", "succeeded", "failed"]),
  created_at: timestampSchema,
  interviews: z.array(personaInterviewSchema).min(2).max(8),
}).strict().superRefine((value, context) => {
  if (value.interviews.length !== value.persona_count) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["interviews"], message: "interview count must match persona_count" });
  }
  if (new Set(value.interviews.map((item) => item.persona.id)).size !== value.interviews.length) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["interviews"], message: "Personas must be unique" });
  }
  const contextMismatch = value.interviews.some((item) => item.report_id !== value.report_id
    || item.report_sha256 !== value.report_sha256
    || item.cohort_id !== value.cohort_id
    || item.cohort_sha256 !== value.cohort_sha256
    || item.question !== value.question
    || item.model_name !== value.model_name
    || item.semantic_config_sha256 !== value.semantic_config_sha256);
  if (contextMismatch) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["interviews"], message: "interviews must match the session context" });
  }
  const statuses = value.interviews.map((item) => item.status);
  const expectedStatus = statuses.every((status) => status === "queued")
    ? "queued"
    : statuses.some((status) => status === "queued" || status === "running")
      ? "running"
      : statuses.every((status) => status === "succeeded") ? "succeeded" : "failed";
  if (value.status !== expectedStatus) {
    context.addIssue({ code: z.ZodIssueCode.custom, path: ["status"], message: "status must be derived from interviews" });
  }
});

export const personaInterviewSessionsResponseSchema = z.object({
  items: z.array(personaInterviewSessionSchema),
  total: z.number().int().nonnegative(),
}).strict();

export type PersonaInterview = z.infer<typeof personaInterviewSchema>;
export type PersonaInterviewsResponse = z.infer<typeof personaInterviewsResponseSchema>;
export type PersonaInterviewSession = z.infer<typeof personaInterviewSessionSchema>;
export type PersonaInterviewSessionsResponse = z.infer<typeof personaInterviewSessionsResponseSchema>;

export function fetchPersonaInterviews(
  reportId: string,
  signal: AbortSignal,
): Promise<PersonaInterviewsResponse> {
  return getJson(
    `/api/v2/decision-reports/${encodeURIComponent(reportId)}/persona-interviews`,
    personaInterviewsResponseSchema,
    signal,
  );
}

export function createPersonaInterview(
  reportId: string,
  personaId: string,
  question: string,
  signal: AbortSignal,
): Promise<PersonaInterview> {
  return postJson(
    `/api/v2/decision-reports/${encodeURIComponent(reportId)}/persona-interviews`,
    { persona_id: personaId, question },
    personaInterviewSchema,
    signal,
  );
}

export function fetchPersonaInterviewSessions(
  reportId: string,
  signal: AbortSignal,
): Promise<PersonaInterviewSessionsResponse> {
  return getJson(
    `/api/v2/decision-reports/${encodeURIComponent(reportId)}/persona-interview-sessions`,
    personaInterviewSessionsResponseSchema,
    signal,
  );
}

export function createPersonaInterviewSession(
  reportId: string,
  personaIds: readonly string[],
  question: string,
  signal: AbortSignal,
): Promise<PersonaInterviewSession> {
  return postJson(
    `/api/v2/decision-reports/${encodeURIComponent(reportId)}/persona-interview-sessions`,
    { persona_ids: personaIds, question },
    personaInterviewSessionSchema,
    signal,
  );
}
