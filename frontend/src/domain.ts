export type SectionId =
  | "overview"
  | "projects"
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
  "overview" | "projects" | "threads" | "media" | "policy" | "world" | "decisions" | "personas" | "tasks" | "runs" | "reports"
>;

export const navigationItems: readonly NavigationItem[] = [
  {
    id: "overview",
    marker: "SO",
    label: "态势总览",
    description: "Overview",
    state: "available",
  },
  {
    id: "projects",
    marker: "PJ",
    label: "研究项目",
    description: "单次群体模拟研究",
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
    label: "媒体证据",
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
    label: "世界与图谱",
    description: "World model",
    state: "available",
  },
  {
    id: "decisions",
    marker: "DX",
    label: "历史实验",
    description: "旧版实验档案",
    state: "available",
  },
  {
    id: "personas",
    marker: "PW",
    label: "模拟人群",
    description: "合成人群工作区",
    state: "available",
  },
  {
    id: "tasks",
    marker: "TG",
    label: "评测中心",
    description: "Capability catalog",
    state: "available",
  },
  {
    id: "runs",
    marker: "RN",
    label: "模拟运行",
    description: "群体模拟运行",
    state: "available",
  },
  {
    id: "reports",
    marker: "RP",
    label: "报告与交互",
    description: "研究报告",
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
