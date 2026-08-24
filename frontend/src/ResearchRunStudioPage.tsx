import { ApiErrorPanel } from "./ApiErrorPanel";
import { ProjectRuns } from "./ResearchProjectsPage";
import { formatProductResourceTitle } from "./productPresentation";
import type { NativeRunStudioRoute, RunStudioRoute } from "./runStudioRoute";
import { useCohorts } from "./usePopulations";
import { useResearchProjects } from "./useResearchProjects";
import "./researchRunStudio.css";

interface ResearchRunStudioPageProps {
  readonly route: NativeRunStudioRoute;
  readonly onRouteChange: (route: RunStudioRoute) => void;
}

export function ResearchRunStudioPage({
  route,
  onRouteChange,
}: ResearchRunStudioPageProps): JSX.Element {
  const projects = useResearchProjects();
  const cohorts = useCohorts();
  const selectedProject = projects.state.status === "success"
    ? projects.state.data.items.find((project) => project.id === route.projectId) ?? null
    : null;
  const selectedProjectMissing = projects.state.status === "success"
    && route.projectId !== null
    && selectedProject === null;

  return (
    <section className="research-run-studio" aria-labelledby="research-run-studio-title">
      <header className="research-run-studio-hero">
        <div>
          <span>SANDOWL / 原生模拟运行</span>
          <h1 id="research-run-studio-title">从研究项目启动一次独立模拟</h1>
          <p>选择已经绑定冻结证据的研究项目，再为这一次运行明确选择合成人群、模拟要求和人物实际看到的起始内容。每次运行独立封存，不创建基线或备选方案。</p>
        </div>
        <ol aria-label="原生运行步骤">
          <li data-current={route.projectId === null}><span>1</span>选择项目</li>
          <li data-current={route.projectId !== null && route.runId === null}><span>2</span>定义并运行</li>
          <li data-current={route.runId !== null}><span>3</span>查看记录</li>
        </ol>
      </header>

      <div className="research-run-studio-layout">
        <aside className="research-run-projects" aria-labelledby="research-run-projects-title">
          <header>
            <div>
              <span>研究上下文</span>
              <h2 id="research-run-projects-title">选择研究项目</h2>
            </div>
            <button type="button" onClick={projects.reload}>刷新</button>
          </header>
          {projects.state.status === "loading" ? <p role="status">正在读取研究项目…</p> : null}
          {projects.state.status === "error" ? <ApiErrorPanel title="无法读取研究项目" error={projects.state.error} isRetrying={false} onRetry={projects.reload} /> : null}
          {projects.state.status === "success" && projects.state.data.items.length === 0 ? <div className="research-run-empty"><strong>还没有研究项目</strong><p>先到“研究项目”绑定冻结证据并写明研究问题，然后再启动模拟。</p><a href="#/projects">创建研究项目</a></div> : null}
          {projects.state.status === "success" ? <ol>{projects.state.data.items.map((project) => <li key={project.id}><button type="button" aria-pressed={project.id === route.projectId} onClick={() => onRouteChange({ mode: "native", projectId: project.id, runId: null })}><strong>{formatProductResourceTitle(project.title)}</strong><span>{project.research_question}</span><small>{project.graph === null ? "历史项目 · 只读" : "图谱绑定项目"}</small></button></li>)}</ol> : null}
          <footer>
            <details>
              <summary>历史兼容档案</summary>
              <p>旧平台验证与多方案实验只用于回查，不属于当前研究项目流程。</p>
              <a href="#/runs?mode=platform">打开历史平台验证归档（只读）</a>
            </details>
          </footer>
        </aside>

        <section className="research-run-stage">
          {selectedProjectMissing ? <div className="research-run-route-error" role="alert"><strong>找不到地址中的研究项目</strong><p>系统没有自动选择其他项目，请从左侧目录重新选择。</p></div> : null}
          {route.projectId === null ? <div className="research-run-stage-empty" role="status"><strong>先选择一个研究项目</strong><p>项目决定本次运行使用的冻结证据和研究问题；系统不会自动打开第一条记录。</p></div> : null}
          {selectedProject !== null ? (
            <article className="research-run-project">
              <header>
                <div>
                  <span>当前研究上下文</span>
                  <h2>{formatProductResourceTitle(selectedProject.title)}</h2>
                  <p>{selectedProject.research_question}</p>
                </div>
                <dl>
                  <div><dt>证据快照</dt><dd><code>{selectedProject.snapshot.snapshot_sha256.slice(0, 12)}…</code></dd></div>
                  <div><dt>上下文</dt><dd>{selectedProject.graph === null ? "历史只读" : `${selectedProject.graph.node_count} 实体 / ${selectedProject.graph.edge_count} 关系`}</dd></div>
                </dl>
              </header>
              {cohorts.state.status === "error" ? <ApiErrorPanel title="无法读取模拟人群" error={cohorts.state.error} isRetrying={cohorts.state.isRetrying} onRetry={cohorts.reload} /> : null}
              <ProjectRuns
                project={selectedProject}
                cohorts={cohorts.state.data?.items ?? []}
                selectedRunId={route.runId}
                onSelectRun={(runId) => onRouteChange({
                  mode: "native",
                  projectId: selectedProject.id,
                  runId,
                })}
              />
            </article>
          ) : null}
        </section>
      </div>
    </section>
  );
}
