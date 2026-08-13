import { useCallback, useEffect, useState } from "react";

import { AppShell } from "./AppShell";
import {
  navigationItems,
  requireNavigationItem,
  type SectionId,
} from "./domain";
import { DecisionReportsPage } from "./DecisionReportsPage";
import { DecisionThreadsPage, createDecisionThreadHash } from "./DecisionThreadsPage";
import { MediaPage } from "./MediaPage";
import { OasisPlatformSmokePage } from "./OasisPlatformSmokePage";
import { OverviewPage } from "./OverviewPage";
import { PersonaWorldPage } from "./PersonaWorldPage";
import { ScenarioPage } from "./ScenarioPage";
import { TaskGalleryPage } from "./TaskGalleryPage";
import { WorldModelPage } from "./WorldModelPage";
import {
  createRunStudioHash,
  resolveRunStudioRoute,
  type RunStudioRoute,
} from "./runStudioRoute";

function renderActivePage(
  activeSection: SectionId,
  onNavigate: (sectionId: SectionId) => void,
  runStudioRoute: RunStudioRoute | null,
  onRunStudioRouteChange: (route: RunStudioRoute) => void,
  resourceId: string | null,
): JSX.Element {
  if (activeSection === "overview") {
    return <OverviewPage onNavigate={onNavigate} />;
  }

  if (activeSection === "media") {
    return <MediaPage />;
  }

  if (activeSection === "threads") {
    return (
      <DecisionThreadsPage
        selectedThreadId={resourceId}
        onSelectThread={(threadId) => {
          window.location.hash = createDecisionThreadHash(threadId);
        }}
      />
    );
  }

  if (activeSection === "world") {
    return <WorldModelPage />;
  }

  if (activeSection === "decisions") {
    return <ScenarioPage />;
  }

  if (activeSection === "personas") {
    return <PersonaWorldPage />;
  }

  if (activeSection === "tasks") {
    return <TaskGalleryPage initialTaskId={resourceId} />;
  }

  if (activeSection === "runs") {
    if (runStudioRoute === null) {
      throw new Error("Run Studio route is missing for the runs workspace.");
    }

    return (
      <OasisPlatformSmokePage
        route={runStudioRoute}
        onRouteChange={onRunStudioRouteChange}
      />
    );
  }

  if (activeSection === "reports") {
    return <DecisionReportsPage initialExperimentId={resourceId} />;
  }

  throw new Error(`Unsupported application section: ${String(activeSection)}`);
}

function createSectionHref(sectionId: SectionId): string {
  return `#/${sectionId}`;
}

type HashRoute =
  | {
      readonly status: "resolved";
      readonly section: SectionId;
      readonly runStudioRoute: RunStudioRoute | null;
      readonly resourceId: string | null;
    }
  | { readonly status: "invalid"; readonly hash: string; readonly message: string };

export function resolveSectionFromHash(hash: string): HashRoute {
  if (hash === "" || hash === "#") {
    return {
      status: "resolved",
      section: "overview",
      runStudioRoute: null,
      resourceId: null,
    };
  }

  if (!hash.startsWith("#/")) {
    return {
      status: "invalid",
      hash,
      message: `无法解析地址“${hash}”。有效地址为：${navigationItems
        .map((item) => createSectionHref(item.id))
        .join("、")}。`,
    };
  }

  const routeValue = hash.slice(2);
  const queryIndex = routeValue.indexOf("?");
  const sectionName = queryIndex === -1 ? routeValue : routeValue.slice(0, queryIndex);
  const query = queryIndex === -1 ? "" : routeValue.slice(queryIndex + 1);
  const section = navigationItems.find((item) => item.id === sectionName);

  if (section === undefined) {
    return {
      status: "invalid",
      hash,
      message: `SandOwl 中不存在“${sectionName}”工作区。有效工作区为：${navigationItems
        .map((item) => item.id)
        .join("、")}。`,
    };
  }

  if (query !== "" && !["runs", "threads", "reports", "tasks"].includes(section.id)) {
    return {
      status: "invalid",
      hash,
      message: `工作区“${section.id}”不接受查询参数。`,
    };
  }

  if (section.id === "runs") {
    const result = resolveRunStudioRoute(query);

    if (result.status === "invalid") {
      return {
        status: "invalid",
        hash,
        message: result.message,
      };
    }

    return {
      status: "resolved",
      section: section.id,
      runStudioRoute: result.route,
      resourceId: null,
    };
  }

  if (section.id === "tasks") {
    const parameters = new URLSearchParams(query);
    if ([...parameters.keys()].some((name) => name !== "task")) {
      return { status: "invalid", hash, message: "Task Gallery 包含不支持的查询参数。" };
    }
    const taskValues = parameters.getAll("task");
    if (taskValues.length > 1) {
      return { status: "invalid", hash, message: "Task Gallery 的 task 参数不能重复。" };
    }
    const taskId = taskValues[0] ?? null;
    if (taskId !== null && taskId !== "survey") {
      return { status: "invalid", hash, message: `Task Gallery 中不存在任务“${taskId}”。` };
    }
    return { status: "resolved", section: section.id, runStudioRoute: null, resourceId: taskId };
  }

  if (section.id === "threads" || section.id === "reports") {
    const parameters = new URLSearchParams(query);
    const expectedName = section.id === "threads" ? "thread_id" : "experiment_id";
    if ([...parameters.keys()].some((name) => name !== expectedName)) {
      return {
        status: "invalid",
        hash,
        message: `工作区“${section.id}”包含不支持的查询参数。`,
      };
    }
    const resourceId = parameters.get(expectedName);
    const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
    if (resourceId !== null && !uuidPattern.test(resourceId)) {
      return {
        status: "invalid",
        hash,
        message: `${expectedName} 必须是有效 UUID。`,
      };
    }
    return {
      status: "resolved",
      section: section.id,
      runStudioRoute: null,
      resourceId,
    };
  }

  return {
    status: "resolved",
    section: section.id,
    runStudioRoute: null,
    resourceId: null,
  };
}

function useHashRoute(): readonly [HashRoute, (sectionId: SectionId) => void] {
  const [route, setRoute] = useState<HashRoute>(() =>
    resolveSectionFromHash(window.location.hash),
  );

  useEffect(() => {
    if (window.location.hash === "" || window.location.hash === "#") {
      window.history.replaceState(null, "", createSectionHref("overview"));
    }

    const syncRouteFromHash = (): void => {
      setRoute(resolveSectionFromHash(window.location.hash));
    };

    window.addEventListener("hashchange", syncRouteFromHash);

    return () => {
      window.removeEventListener("hashchange", syncRouteFromHash);
    };
  }, []);

  const navigate = useCallback((sectionId: SectionId): void => {
    window.location.hash = createSectionHref(sectionId);
  }, []);

  return [route, navigate] as const;
}

function RouteErrorPage({ route }: { readonly route: Extract<HashRoute, { status: "invalid" }> }): JSX.Element {
  return (
    <div className="workspace">
      <header className="workspace-header">
        <div>
          <span className="breadcrumb">SandOwl / Route error</span>
          <h1 id="workspace-title">地址无法解析</h1>
        </div>
      </header>
      <main className="workspace-main" aria-labelledby="workspace-title">
        <div className="module-page">
          <section className="module-intro" aria-labelledby="route-error-title">
            <div className="module-code" aria-hidden="true">404</div>
            <div>
              <h2 id="route-error-title">这个工作区地址不存在</h2>
              <p>系统没有改写或忽略该地址，以免把路由错误误认为真实工作区内容。</p>
            </div>
          </section>
          <section className="module-workbench" aria-labelledby="route-diagnosis-title">
            <div className="workbench-heading" role="alert">
              <div>
                <h3 id="route-diagnosis-title">路由诊断</h3>
                <p>{route.message}</p>
              </div>
              <span>{route.hash}</span>
            </div>
          </section>
          <aside className="implementation-note" aria-label="恢复导航">
            <strong>返回安全入口</strong>
            <p>回到决策工作台后，可从主导航重新进入需要的模块。</p>
            <a className="button button-primary" href={createSectionHref("overview")}>返回决策工作台</a>
          </aside>
        </div>
      </main>
    </div>
  );
}

export function App(): JSX.Element {
  const [route, navigate] = useHashRoute();
  const updateRunStudioRoute = useCallback((nextRoute: RunStudioRoute): void => {
    window.location.hash = createRunStudioHash(nextRoute);
  }, []);

  if (route.status === "invalid") {
    return <RouteErrorPage route={route} />;
  }

  const activeSection = route.section;
  const activeItem = requireNavigationItem(activeSection);

  return (
    <AppShell
      activeSection={activeSection}
      activeItem={activeItem}
      navigation={navigationItems}
      createSectionHref={createSectionHref}
    >
      {renderActivePage(
        activeSection,
        navigate,
        route.runStudioRoute,
        updateRunStudioRoute,
        route.resourceId,
      )}
    </AppShell>
  );
}
