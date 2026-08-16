const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;

export interface WorldRoute {
  readonly worldModelId: string | null;
  readonly snapshotId: string | null;
  readonly evidenceId: string | null;
}

export type WorldRouteResolution =
  | { readonly status: "resolved"; readonly route: WorldRoute }
  | { readonly status: "invalid"; readonly message: string };

export function resolveWorldRoute(query: string): WorldRouteResolution {
  const parameters = new URLSearchParams(query);
  const supported = new Set(["world_model_id", "snapshot_id", "evidence_id"]);
  const unknown = [...parameters.keys()].filter((name) => !supported.has(name));
  if (unknown.length > 0) {
    return { status: "invalid", message: `World 工作区包含不支持的参数：${unknown.join("、")}。` };
  }
  const repeated = [...supported].filter((name) => parameters.getAll(name).length > 1);
  if (repeated.length > 0) {
    return { status: "invalid", message: `World 参数不能重复：${repeated.join("、")}。` };
  }
  const worldModelId = parameters.get("world_model_id");
  const snapshotId = parameters.get("snapshot_id");
  const evidenceId = parameters.get("evidence_id");
  if (worldModelId !== null && !uuidPattern.test(worldModelId)) {
    return { status: "invalid", message: "world_model_id 必须是有效 UUID。" };
  }
  if (snapshotId !== null && !uuidPattern.test(snapshotId)) {
    return { status: "invalid", message: "snapshot_id 必须是有效 UUID。" };
  }
  if (evidenceId !== null && !uuidPattern.test(evidenceId)) {
    return { status: "invalid", message: "evidence_id 必须是有效 UUID。" };
  }
  if (snapshotId !== null && worldModelId === null) {
    return { status: "invalid", message: "snapshot_id 必须与 world_model_id 一起使用。" };
  }
  return { status: "resolved", route: { worldModelId, snapshotId, evidenceId } };
}

export function createWorldHash(route: WorldRoute): string {
  const parameters = new URLSearchParams();
  if (route.worldModelId !== null) parameters.set("world_model_id", route.worldModelId);
  if (route.snapshotId !== null) {
    if (route.worldModelId === null) {
      throw new Error("Cannot create a World snapshot deep link without a WorldModel identity.");
    }
    parameters.set("snapshot_id", route.snapshotId);
  }
  if (route.evidenceId !== null) parameters.set("evidence_id", route.evidenceId);
  const query = parameters.toString();
  return query === "" ? "#/world" : `#/world?${query}`;
}
