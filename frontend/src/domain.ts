export type SectionId =
  | "overview"
  | "threads"
  | "media"
  | "policy"
  | "world"
  | "decisions"
  | "personas"
  | "tasks"
  | "runs"
  | "reports";

export interface NavigationItem {
  readonly id: SectionId;
  readonly marker: string;
  readonly label: string;
  readonly description: string;
  readonly state: "available" | "migrating";
}

export interface ModuleDefinition {
  readonly sectionId: MigratingSectionId;
  readonly summary: string;
  readonly outcome: string;
  readonly responsibilities: readonly string[];
  readonly source: string;
}

export type MigratingSectionId = Exclude<
  SectionId,
  "overview" | "threads" | "media" | "policy" | "world" | "decisions" | "personas" | "tasks" | "runs" | "reports"
>;

export const navigationItems: readonly NavigationItem[] = [
  {
    id: "overview",
    marker: "DC",
    label: "决策工作台",
    description: "Overview",
    state: "available",
  },
  {
    id: "threads",
    marker: "DT",
    label: "决策任务",
    description: "Decision portfolio",
    state: "available",
  },
  {
    id: "media",
    marker: "MI",
    label: "媒体情报",
    description: "Media intelligence",
    state: "available",
  },
  {
    id: "policy",
    marker: "PE",
    label: "政策证据",
    description: "Policy evidence",
    state: "available",
  },
  {
    id: "world",
    marker: "WM",
    label: "世界模型",
    description: "World model",
    state: "available",
  },
  {
    id: "decisions",
    marker: "DX",
    label: "决策实验",
    description: "Decision experiments",
    state: "available",
  },
  {
    id: "personas",
    marker: "PW",
    label: "Persona World",
    description: "Population workspace",
    state: "available",
  },
  {
    id: "tasks",
    marker: "TG",
    label: "Task Gallery",
    description: "Capability catalog",
    state: "available",
  },
  {
    id: "runs",
    marker: "RN",
    label: "Playground",
    description: "Experiment cockpit",
    state: "available",
  },
  {
    id: "reports",
    marker: "RP",
    label: "报告",
    description: "Reports",
    state: "available",
  },
];

export const moduleDefinitions: Readonly<
  Record<MigratingSectionId, ModuleDefinition>
> = {
};

export function requireNavigationItem(sectionId: SectionId): NavigationItem {
  const item = navigationItems.find((candidate) => candidate.id === sectionId);

  if (item === undefined) {
    throw new Error(`Navigation item is missing for section: ${sectionId}`);
  }

  return item;
}
