import { z } from "zod";

import { getJson, postJson } from "./apiClient";
import { sha256DigestSchema } from "./mediaContracts";

const endpoint = "/api/v2/decision-reports";
const uuidSchema = z.string().uuid();
const timestampSchema = z.string().datetime({ offset: true });
const titleSchema = z.string().trim().min(1).max(300).regex(/^[^\r\n]+$/u);
const metricNameSchema = z.enum([
  "observed_action_count",
  "authored_content_count",
  "reaction_count",
  "do_nothing_count",
]);

export const decisionReportMetricSchema = z.object({
  metric: metricNameSchema,
  alternative_id: uuidSchema,
  alternative_name: z.string().trim().min(1).max(200),
  baseline_mean: z.number().finite(),
  alternative_mean: z.number().finite(),
  mean_delta: z.number().finite(),
  stddev_delta: z.number().finite().nonnegative(),
  paired_seed_count: z.number().int().min(1).max(2),
}).strict();

export const decisionReportSectionSchema = z.object({
  position: z.number().int().min(0).max(3),
  kind: z.enum(["scope", "comparison", "limitations", "provenance"]),
  title: titleSchema,
  body_markdown: z.string().min(1).max(40_000),
  metrics: z.array(decisionReportMetricSchema),
}).strict();

export const decisionReportSchema = z.object({
  id: uuidSchema,
  experiment_id: uuidSchema,
  experiment_sha256: sha256DigestSchema,
  scenario_id: uuidSchema,
  scenario_sha256: sha256DigestSchema,
  cohort_id: uuidSchema,
  cohort_sha256: sha256DigestSchema,
  title: titleSchema,
  report_sha256: sha256DigestSchema,
  generator_version: z.literal("deterministic-findings/v1"),
  created_at: timestampSchema,
  sections: z.array(decisionReportSectionSchema).length(4),
}).strict().superRefine((value, context) => {
  const positions = value.sections.map((section) => section.position);
  const kinds = value.sections.map((section) => section.kind);
  if (positions.join(",") !== "0,1,2,3") {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "Report sections must be contiguous" });
  }
  if (kinds.join(",") !== "scope,comparison,limitations,provenance") {
    context.addIssue({ code: z.ZodIssueCode.custom, message: "Report outline is invalid" });
  }
});

export const decisionReportsResponseSchema = z.object({
  items: z.array(decisionReportSchema),
  total: z.number().int().nonnegative(),
}).strict();

export type DecisionReport = z.infer<typeof decisionReportSchema>;
export type DecisionReportMetric = z.infer<typeof decisionReportMetricSchema>;
export type DecisionReportsResponse = z.infer<typeof decisionReportsResponseSchema>;

export function fetchDecisionReports(signal: AbortSignal): Promise<DecisionReportsResponse> {
  return getJson(endpoint, decisionReportsResponseSchema, signal);
}

export function generateDecisionReport(
  experimentId: string,
  signal: AbortSignal,
): Promise<DecisionReport> {
  return postJson(
    `${endpoint}/from-experiment/${encodeURIComponent(experimentId)}`,
    {},
    decisionReportSchema,
    signal,
  );
}

export function createDecisionReportMarkdownUrl(reportId: string): string {
  return `${endpoint}/${encodeURIComponent(reportId)}/markdown`;
}
