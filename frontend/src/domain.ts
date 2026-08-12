export type SectionId =
  | "overview"
  | "media"
  | "companies"
  | "world"
  | "decisions"
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
  "overview" | "media" | "companies" | "world" | "decisions" | "runs"
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
    id: "media",
    marker: "MI",
    label: "媒体情报",
    description: "Media intelligence",
    state: "available",
  },
  {
    id: "companies",
    marker: "CE",
    label: "企业证据",
    description: "Company evidence",
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
    id: "runs",
    marker: "RN",
    label: "运行",
    description: "Runs",
    state: "available",
  },
  {
    id: "reports",
    marker: "RP",
    label: "报告",
    description: "Reports",
    state: "migrating",
  },
];

export const moduleDefinitions: Readonly<
  Record<MigratingSectionId, ModuleDefinition>
> = {
  reports: {
    sectionId: "reports",
    summary: "在不混淆现实证据和模拟结果的前提下，对比方案并形成判断。",
    outcome: "输出带证据、限制条件和引擎溯源的决策报告。",
    responsibilities: ["方案指标比较", "不确定性与限制", "证据引用与报告导出"],
    source: "Decision Core",
  },
};

export function requireNavigationItem(sectionId: SectionId): NavigationItem {
  const item = navigationItems.find((candidate) => candidate.id === sectionId);

  if (item === undefined) {
    throw new Error(`Navigation item is missing for section: ${sectionId}`);
  }

  return item;
}
