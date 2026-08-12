import { z } from "zod";

import { getJson } from "./apiClient";

const capabilityStateSchema = z.enum(["contract_ready", "runtime_ready"]);

const capabilityDescriptorSchema = z.object({
  name: z.string().trim().min(1),
  state: capabilityStateSchema,
  source: z.string().trim().min(1),
  contracts: z.array(z.string().trim().min(1)).min(1),
});

const systemCapabilitiesSchema = z.object({
  api_version: z.string().trim().min(1),
  product: z.string().trim().min(1),
  capabilities: z.array(capabilityDescriptorSchema).min(1),
});

export type CapabilityDescriptor = z.infer<typeof capabilityDescriptorSchema>;
export type SystemCapabilities = z.infer<typeof systemCapabilitiesSchema>;

const capabilitiesEndpoint = "/api/v2/system/capabilities";

export function fetchSystemCapabilities(signal: AbortSignal): Promise<SystemCapabilities> {
  return getJson(capabilitiesEndpoint, systemCapabilitiesSchema, signal);
}
