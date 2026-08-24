import { z } from "zod";

const idSchema = z.string().uuid();
const timestampSchema = z.string().datetime({ offset: true });
const digestSchema = z.string().regex(/^[a-f0-9]{64}$/);

export const nativeMediaCollectionConfigSchema = z.object({
  source_id: idSchema,
  enabled: z.boolean(),
  collection_mode: z.enum(["rss", "web"]),
  feed_url: z.string().nullable(),
  poll_interval_seconds: z.number().int().min(300).max(86400),
  config_sha256: digestSchema,
  last_attempt_at: timestampSchema.nullable(),
  last_success_at: timestampSchema.nullable(),
  consecutive_failures: z.number().int().nonnegative(),
}).strict();

export const nativeMediaCollectionStatusSchema = z.object({
  generated_at: timestampSchema,
  worker_online: z.boolean(),
  enabled_source_count: z.number().int().nonnegative(),
  due_source_count: z.number().int().nonnegative(),
  latest_runs: z.array(z.object({
    id: idSchema,
    source_id: idSchema,
    status: z.enum(["running", "succeeded", "failed", "skipped"]),
    worker_id: z.string().min(1),
    config_sha256: digestSchema,
    scheduled_at: timestampSchema,
    started_at: timestampSchema,
    completed_at: timestampSchema.nullable(),
    articles_discovered: z.number().int().nonnegative(),
    articles_inserted: z.number().int().nonnegative(),
    articles_existing: z.number().int().nonnegative(),
    error_code: z.string().nullable(),
    error_message: z.string().nullable(),
  }).strict()).max(20),
  active_alerts: z.array(z.object({
    id: idSchema,
    source_id: idSchema,
    kind: z.enum(["consecutive_failures", "no_content"]),
    severity: z.enum(["warning", "critical"]),
    message: z.string().min(1),
    observed_at: timestampSchema,
  }).strict()).max(50),
  limitations: z.array(z.string().min(1)).min(1),
}).strict();

export type NativeMediaCollectionStatus = z.infer<typeof nativeMediaCollectionStatusSchema>;

export async function fetchNativeMediaCollectionStatus(
  signal: AbortSignal,
): Promise<NativeMediaCollectionStatus> {
  const response = await fetch("/api/v2/media/collection/status", { signal });
  if (!response.ok) throw new Error(`读取原生采集状态失败（HTTP ${response.status}）`);
  return nativeMediaCollectionStatusSchema.parse(await response.json());
}

export async function createNativeMediaSource(
  request: {
    readonly name: string;
    readonly country_code: string;
    readonly homepage_url: string;
    readonly media_type: "newspaper" | "agency" | "broadcast" | "online";
    readonly language: string;
    readonly collection_mode: "rss" | "web";
    readonly feed_url: string | null;
    readonly poll_interval_seconds: number;
  },
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch("/api/v2/media/sources", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(request),
    signal,
  });
  if (!response.ok) throw new Error(`新增媒体来源失败（HTTP ${response.status}）`);
  nativeMediaCollectionConfigSchema.parse(await response.json());
}
