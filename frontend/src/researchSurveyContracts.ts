import { z } from "zod";

import { getJson, postJson } from "./apiClient";
import { sha256DigestSchema } from "./mediaContracts";
import { parentProgressSchema, type ParentProgress } from "./parentProgress";

const endpoint = "/api/v2/research-surveys";
const id = z.string().uuid();
const text = z.string().trim().min(1);
const timestamp = z.string().datetime({ offset: true });
const status = z.enum(["queued", "running", "succeeded", "failed"]);
const projectRef = z.object({ id, title: text.max(300), research_question: text.max(2000), project_sha256: sha256DigestSchema }).strict();
const runRef = z.object({ id, simulation_requirement: text.max(4000), initial_post: text.max(4000), run_spec_sha256: sha256DigestSchema }).strict();
const cohortRef = z.object({ id, title: text.max(200), cohort_sha256: sha256DigestSchema, dataset_sha256: sha256DigestSchema, persona_count: z.number().int().min(1).max(8) }).strict();
const personaRef = z.object({ id, position: z.number().int().min(0).max(7), persona_id: text.max(128), display_name: text.max(200), profile_sha256: sha256DigestSchema }).strict();
const instrument = z.object({ schema_version: z.literal("single-context-observation/v1"), instrument_sha256: sha256DigestSchema, title: z.literal("Single-context observation"), description: text.max(4000) }).strict();
const answers = z.tuple([
  z.object({ position: z.literal(0), question_id: z.literal("context_clarity"), type: z.literal("likert"), value: z.number().int().min(1).max(5) }).strict(),
  z.object({ position: z.literal(1), question_id: z.literal("attention_priority"), type: z.literal("single_choice"), value: z.enum(["evidence", "process", "timing", "impact"]) }).strict(),
  z.object({ position: z.literal(2), question_id: z.literal("unanswered_question"), type: z.literal("free_text"), value: text.max(2000) }).strict(),
]);
const trial = z.object({ id, status, persona: personaRef, trial_sha256: sha256DigestSchema, created_at: timestamp, started_at: timestamp.nullable(), completed_at: timestamp.nullable(), result: z.object({ runner_version: z.literal("1.0.0"), model_name: text.max(200), survey_config_sha256: sha256DigestSchema, prompt_schema_version: z.literal("sandowl-research-survey/v1"), answers_sha256: sha256DigestSchema, answers }).strict().nullable(), error: z.object({ code: text.max(128), message: text.max(4000) }).strict().nullable() }).strict();
const summaryObject = z.object({ id, status, project: projectRef, run: runRef, cohort: cohortRef, trial_count: z.number().int().min(1).max(8), succeeded_trial_count: z.number().int().min(0).max(8), failed_trial_count: z.number().int().min(0).max(8), model_name: text.max(200), survey_config_sha256: sha256DigestSchema, prompt_schema_version: z.literal("sandowl-research-survey/v1"), instrument_schema_version: z.literal("single-context-observation/v1"), instrument_sha256: sha256DigestSchema, survey_sha256: sha256DigestSchema, created_at: timestamp }).strict();
export const researchSurveySummarySchema = summaryObject;
export const researchSurveyDetailSchema = summaryObject.extend({ instrument, trials: z.array(trial).min(1).max(8), aggregate: z.object({ succeeded_trial_count: z.number().int().min(0).max(8), failed_trial_count: z.number().int().min(0).max(8), context_clarity_mean: z.number().min(1).max(5).nullable(), attention_priority: z.object({ evidence: z.number().int().min(0).max(8), process: z.number().int().min(0).max(8), timing: z.number().int().min(0).max(8), impact: z.number().int().min(0).max(8) }).strict(), unanswered_questions: z.array(text.max(4000)).max(8), limitations: z.array(text.max(4000)).min(1) }).strict() }).strict();
export const researchSurveyReadinessSchema = z.object({ engine: z.literal("matraix-survey"), runner_version: z.literal("1.0.0"), survey_runtime_ready: z.boolean(), live_worker_count: z.number().int().nonnegative(), model_name: text.max(200).nullable(), survey_config_sha256: sha256DigestSchema.nullable(), prompt_schema_version: z.literal("sandowl-research-survey/v1").nullable(), instrument_schema_version: z.literal("single-context-observation/v1"), limitations: z.array(text.max(4000)).min(1) }).strict();
const response = z.object({ items: z.array(researchSurveySummarySchema), total: z.number().int().nonnegative() }).strict();
const createRequest = z.object({ research_project_id: id, research_simulation_run_id: id }).strict();

export type ResearchSurveySummary = z.infer<typeof researchSurveySummarySchema>;
export type ResearchSurveyDetail = z.infer<typeof researchSurveyDetailSchema>;
export type ResearchSurveyTrial = z.infer<typeof trial>;
export type ResearchSurveyReadiness = z.infer<typeof researchSurveyReadinessSchema>;
export const fetchResearchSurveys = (signal: AbortSignal): Promise<z.infer<typeof response>> => getJson(endpoint, response, signal);
export const fetchResearchSurvey = (surveyId: string, signal: AbortSignal): Promise<ResearchSurveyDetail> => getJson(`${endpoint}/${id.parse(surveyId)}`, researchSurveyDetailSchema, signal);
export const fetchResearchSurveyProgress = (surveyId: string, signal: AbortSignal): Promise<ParentProgress> => getJson(`${endpoint}/${id.parse(surveyId)}/progress`, parentProgressSchema, signal);
export const fetchResearchSurveyReadiness = (signal: AbortSignal): Promise<ResearchSurveyReadiness> => getJson(`${endpoint}/readiness`, researchSurveyReadinessSchema, signal);
export const createResearchSurvey = (projectId: string, runId: string, signal: AbortSignal): Promise<ResearchSurveyDetail> => postJson(endpoint, createRequest.parse({ research_project_id: projectId, research_simulation_run_id: runId }), researchSurveyDetailSchema, signal);
