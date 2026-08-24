import { describe, expect, it } from "vitest";

import { nativeMediaCollectionStatusSchema } from "./nativeMediaCollectionContracts";

describe("nativeMediaCollectionStatusSchema", () => {
  it("accepts an idle native collector without external AgendaScope state", () => {
    const status = nativeMediaCollectionStatusSchema.parse({
      generated_at: "2026-08-18T14:00:00+08:00",
      worker_online: true,
      enabled_source_count: 0,
      due_source_count: 0,
      latest_runs: [],
      active_alerts: [],
      limitations: ["原生采集不依赖外部数据库。"],
    });
    expect(status.worker_online).toBe(true);
    expect(status.enabled_source_count).toBe(0);
  });
});
