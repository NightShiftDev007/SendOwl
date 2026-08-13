import { z } from "zod";

import { getJson, postJson } from "./apiClient";
import { sha256DigestSchema } from "./mediaContracts";

const uuidSchema = z.string().uuid();
const timestampSchema = z.string().datetime({ offset: true });

export const reportAnswerCitationSchema = z.object({
  position: z.number().int().min(0).max(19),
  article_id: uuidSchema,
  quote: z.string().min(1).max(500),
  start_offset: z.number().int().nonnegative(),
  end_offset: z.number().int().positive(),
}).strict().refine((value) => value.end_offset > value.start_offset, {
  message: "Citation end offset must follow its start offset",
});

export const reportQuestionSchema = z.object({
  id: uuidSchema,
  report_id: uuidSchema,
  report_sha256: sha256DigestSchema,
  graph_id: uuidSchema,
  graph_sha256: sha256DigestSchema,
  question: z.string().trim().min(2).max(1000),
  question_sha256: sha256DigestSchema,
  model_name: z.string().trim().min(1).max(200),
  semantic_config_sha256: sha256DigestSchema,
  prompt_schema_version: z.literal("report-evidence-qa/v1"),
  status: z.enum(["queued", "running", "succeeded", "failed"]),
  created_at: timestampSchema,
  started_at: timestampSchema.nullable(),
  completed_at: timestampSchema.nullable(),
  answer_markdown: z.string().min(1).max(800).nullable(),
  citations: z.array(reportAnswerCitationSchema).max(20),
  answer_sha256: sha256DigestSchema.nullable(),
  error_code: z.string().min(1).max(128).nullable(),
  error_message: z.string().min(1).max(500).nullable(),
}).strict().superRefine((value, context) => {
  const running = value.started_at !== null && value.completed_at === null;
  const terminal = value.started_at !== null && value.completed_at !== null;
  const succeeded = value.answer_markdown !== null
    && value.citations.length > 0
    && value.answer_sha256 !== null
    && value.error_code === null
    && value.error_message === null;
  const failed = value.answer_markdown === null
    && value.citations.length === 0
    && value.answer_sha256 === null
    && value.error_code !== null
    && value.error_message !== null;
  const waiting = value.answer_markdown === null
    && value.citations.length === 0
    && value.answer_sha256 === null
    && value.error_code === null
    && value.error_message === null;
  const valid = value.status === "queued"
    ? value.started_at === null && value.completed_at === null && waiting
    : value.status === "running"
      ? running && waiting
      : value.status === "succeeded"
        ? terminal && succeeded
        : terminal && failed;
  if (!valid) {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "Report question lifecycle is invalid" });
  }
});

export const reportQuestionsResponseSchema = z.object({
  items: z.array(reportQuestionSchema),
  total: z.number().int().nonnegative(),
}).strict();

export type ReportQuestion = z.infer<typeof reportQuestionSchema>;
export type ReportQuestionsResponse = z.infer<typeof reportQuestionsResponseSchema>;

export function fetchReportQuestions(
  reportId: string,
  signal: AbortSignal,
): Promise<ReportQuestionsResponse> {
  return getJson(
    `/api/v2/decision-reports/${encodeURIComponent(reportId)}/questions`,
    reportQuestionsResponseSchema,
    signal,
  );
}

export function createReportQuestion(
  reportId: string,
  question: string,
  signal: AbortSignal,
): Promise<ReportQuestion> {
  return postJson(
    `/api/v2/decision-reports/${encodeURIComponent(reportId)}/questions`,
    { question },
    reportQuestionSchema,
    signal,
  );
}
