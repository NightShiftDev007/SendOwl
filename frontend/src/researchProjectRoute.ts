const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;

export interface ResearchProjectRoute {
  readonly worldModelId: string | null;
  readonly snapshotId: string | null;
  readonly graphId: string | null;
}

export type ResearchProjectRouteResolution =
  | { readonly status: "resolved"; readonly route: ResearchProjectRoute }
  | { readonly status: "invalid"; readonly message: string };

export function resolveResearchProjectRoute(query: string): ResearchProjectRouteResolution {
  const parameters = new URLSearchParams(query);
  const supported = new Set(["world_model_id", "snapshot_id", "graph_id"]);
  const unknown = [...parameters.keys()].filter((name) => !supported.has(name));
  if (unknown.length > 0) {
    return { status: "invalid", message: `研究项目工作区包含不支持的参数：${unknown.join("、")}。` };
  }
  const repeated = [...supported].filter((name) => parameters.getAll(name).length > 1);
  if (repeated.length > 0) {
    return { status: "invalid", message: `研究项目参数不能重复：${repeated.join("、")}。` };
  }
  const worldModelId = parameters.get("world_model_id");
  const snapshotId = parameters.get("snapshot_id");
  const graphId = parameters.get("graph_id");
  if (worldModelId !== null && !uuidPattern.test(worldModelId)) {
    return { status: "invalid", message: "world_model_id 必须是有效 UUID。" };
  }
  if (snapshotId !== null && !uuidPattern.test(snapshotId)) {
    return { status: "invalid", message: "snapshot_id 必须是有效 UUID。" };
  }
  if (graphId !== null && !uuidPattern.test(graphId)) {
    return { status: "invalid", message: "graph_id 必须是有效 UUID。" };
  }
  if ((worldModelId === null) !== (snapshotId === null)) {
    return {
      status: "invalid",
      message: "创建研究项目时，world_model_id 与 snapshot_id 必须一起使用。",
    };
  }
  if (graphId !== null && worldModelId === null) {
    return {
      status: "invalid",
      message: "graph_id 必须与 world_model_id、snapshot_id 一起使用。",
    };
  }
  return { status: "resolved", route: { worldModelId, snapshotId, graphId } };
}

export function createResearchProjectHash(route: ResearchProjectRoute): string {
  if ((route.worldModelId === null) !== (route.snapshotId === null)) {
    throw new Error("Cannot create a Research Project handoff without both WorldModel and snapshot identities.");
  }
  if (route.graphId !== null && route.worldModelId === null) {
    throw new Error("Cannot create a Research Project handoff with a graph alone.");
  }
  if (route.worldModelId === null || route.snapshotId === null) return "#/projects";
  const parameters = new URLSearchParams({
    world_model_id: route.worldModelId,
    snapshot_id: route.snapshotId,
  });
  if (route.graphId !== null) parameters.set("graph_id", route.graphId);
  return `#/projects?${parameters.toString()}`;
}
