import type { ModuleDefinition, NavigationItem } from "./domain";

export interface ModulePageProps {
  readonly definition: ModuleDefinition;
  readonly navigationItem: NavigationItem;
}

export function ModulePage({ definition, navigationItem }: ModulePageProps): JSX.Element {
  return (
    <div className="module-page">
      <section className="module-intro">
        <div className="module-code" aria-hidden="true">
          {navigationItem.marker}
        </div>
        <div>
          <h2>{definition.summary}</h2>
          <p>{definition.outcome}</p>
        </div>
      </section>

      <section className="module-workbench" aria-labelledby="scope-title">
        <div className="workbench-heading">
          <div>
            <h3 id="scope-title">模块迁移中</h3>
            <p>当前路由仅保留信息架构位置，不展示模拟数据，也不代表对应能力已可用。</p>
          </div>
          <span>来源 · {definition.source}</span>
        </div>

        <ol className="responsibility-list">
          {definition.responsibilities.map((responsibility, index) => (
            <li key={responsibility}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <strong>{responsibility}</strong>
              <small>等待真实领域接口与迁移验收</small>
            </li>
          ))}
        </ol>
      </section>

      <aside className="implementation-note" aria-label="实现说明">
        <strong>迁移说明</strong>
        <p>
          这里不会嵌入原项目页面。能力将围绕企业决策领域重新组织，并使用统一的证据、运行和结果契约。
        </p>
      </aside>
    </div>
  );
}
