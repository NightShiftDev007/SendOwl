import { lazy, Suspense, useCallback, useEffect, useState } from "react";

import { AppShell } from "./AppShell";
import {
  navigationItems,
  requireNavigationItem,
  type SectionId,
} from "./domain";
import {
  createMediaHash,
  resolveMediaRoute,
  type MediaRoute,
} from "./mediaRoute";
import {
  createResearchProjectHash,
  resolveResearchProjectRoute,
  type ResearchProjectRoute,
} from "./researchProjectRoute";
import {
  resolveReportWorkspaceRoute,
  type ReportWorkspaceRoute,
} from "./reportWorkspaceRoute";
import {
  createTaskGalleryHash,
  resolveTaskGalleryRoute,
  type TaskGalleryRoute,
} from "./taskGalleryRoute";
import {
  createWorldHash,
  resolveWorldRoute,
  type WorldRoute,
} from "./worldRoute";
import {
  createRunStudioHash,
  resolveRunStudioRoute,
  type RunStudioRoute,
} from "./runStudioRoute";

const DecisionReportsPage = lazy(async () => {
  const module = await import("./DecisionReportsPage");
  return { default: module.DecisionReportsPage };
});
const DecisionThreadsPage = lazy(async () => {
  const module = await import("./DecisionThreadsPage");
  return { default: module.DecisionThreadsPage };
});
const MediaPage = lazy(async () => {
  const module = await import("./MediaPage");
  return { default: module.MediaPage };
});
const OasisPlatformSmokePage = lazy(async () => {
  const module = await import("./OasisPlatformSmokePage");
  return { default: module.OasisPlatformSmokePage };
});
const OverviewPage = lazy(async () => {
  const module = await import("./OverviewPage");
  return { default: module.OverviewPage };
});
const PersonaWorldPage = lazy(async () => {
  const module = await import("./PersonaWorldPage");
  return { default: module.PersonaWorldPage };
});
const PolicyEvidencePage = lazy(async () => {
  const module = await import("./PolicyEvidencePage");
  return { default: module.PolicyEvidencePage };
});
const ResearchProjectsPage = lazy(async () => {
  const module = await import("./ResearchProjectsPage");
  return { default: module.ResearchProjectsPage };
});
const ResearchReportsPage = lazy(async () => {
  const module = await import("./ResearchReportsPage");
  return { default: module.ResearchReportsPage };
});
const ResearchRunStudioPage = lazy(async () => {
  const module = await import("./ResearchRunStudioPage");
  return { default: module.ResearchRunStudioPage };
});
const ScenarioPage = lazy(async () => {
  const module = await import("./ScenarioPage");
  return { default: module.ScenarioPage };
});
const TaskGalleryPage = lazy(async () => {
  const module = await import("./TaskGalleryPage");
  return { default: module.TaskGalleryPage };
});
const WorldModelPage = lazy(async () => {
  const module = await import("./WorldModelPage");
  return { default: module.WorldModelPage };
});

function createDecisionThreadHash(threadId: string | null): string {
  return threadId === null ? "#/threads" : `#/threads?thread_id=${encodeURIComponent(threadId)}`;
}

function PageLoadingFallback(): JSX.Element {
  return (
    <section className="page-loading-fallback" role="status" aria-live="polite">
      <span className="sr-only">正在加载工作区</span>
      <span className="skeleton-block" aria-hidden="true" />
      <span className="skeleton-block" aria-hidden="true" />
      <span className="skeleton-block" aria-hidden="true" />
    </section>
  );
}

function renderActivePage(
  activeSection: SectionId,
  onNavigate: (sectionId: SectionId) => void,
  runStudioRoute: RunStudioRoute | null,
  onRunStudioRouteChange: (route: RunStudioRoute) => void,
  mediaRoute: MediaRoute | null,
  onMediaRouteChange: (route: MediaRoute) => void,
  taskGalleryRoute: TaskGalleryRoute | null,
  onTaskGalleryRouteChange: (route: TaskGalleryRoute) => void,
  worldRoute: WorldRoute | null,
  onWorldRouteChange: (route: WorldRoute) => void,
  researchProjectRoute: ResearchProjectRoute | null,
  onResearchProjectRouteChange: (route: ResearchProjectRoute) => void,
  resourceId: string | null,
  reportWorkspaceRoute: ReportWorkspaceRoute | null,
): JSX.Element {
  if (activeSection === "overview") {
    return (
      <OverviewPage
        onNavigate={onNavigate}
        onOpenMediaTopic={(topicId) => {
          onMediaRouteChange({ topicId, sourceId: null, lens: "topic", country: null });
        }}
      />
    );
  }

  if (activeSection === "media") {
    if (mediaRoute === null) {
      throw new Error("Media route is missing for the media workspace.");
    }

    return <MediaPage route={mediaRoute} onRouteChange={onMediaRouteChange} />;
  }

  if (activeSection === "policy") {
    return <PolicyEvidencePage />;
  }

  if (activeSection === "projects") {
    if (researchProjectRoute === null) {
      throw new Error("Research Project route is missing for the projects workspace.");
    }
    return (
      <ResearchProjectsPage
        route={researchProjectRoute}
        onRouteChange={onResearchProjectRouteChange}
      />
    );
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
    if (worldRoute === null) {
      throw new Error("World route is missing for the World workspace.");
    }
    return <WorldModelPage route={worldRoute} onRouteChange={onWorldRouteChange} />;
  }

  if (activeSection === "decisions") {
    return <ScenarioPage />;
  }

  if (activeSection === "personas") {
    return <PersonaWorldPage />;
  }

  if (activeSection === "tasks") {
    if (taskGalleryRoute === null) {
      throw new Error("Task Gallery route is missing for the tasks workspace.");
    }
    return (
      <TaskGalleryPage
        route={taskGalleryRoute}
        onRouteChange={onTaskGalleryRouteChange}
      />
    );
  }

  if (activeSection === "runs") {
    if (runStudioRoute === null) {
      throw new Error("Run Studio route is missing for the runs workspace.");
    }

    return runStudioRoute.mode === "native"
      ? (
        <ResearchRunStudioPage
          route={runStudioRoute}
          onRouteChange={onRunStudioRouteChange}
        />
      )
      : (
        <OasisPlatformSmokePage
          route={runStudioRoute}
          onRouteChange={onRunStudioRouteChange}
        />
      );
  }

  if (activeSection === "reports") {
    if (reportWorkspaceRoute === null) {
      throw new Error("Report workspace route is missing for the reports workspace.");
    }
    return reportWorkspaceRoute.mode === "legacy"
      ? <DecisionReportsPage initialExperimentId={reportWorkspaceRoute.experimentId} />
      : (
        <ResearchReportsPage
          initialProjectId={reportWorkspaceRoute.projectId}
          initialRunId={reportWorkspaceRoute.runId}
        />
      );
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
      readonly mediaRoute: MediaRoute | null;
      readonly taskGalleryRoute: TaskGalleryRoute | null;
      readonly worldRoute: WorldRoute | null;
      readonly researchProjectRoute?: ResearchProjectRoute;
      readonly resourceId: string | null;
      readonly reportWorkspaceRoute?: ReportWorkspaceRoute;
    }
  | { readonly status: "invalid"; readonly hash: string; readonly message: string };

export function resolveSectionFromHash(hash: string): HashRoute {
  if (hash === "" || hash === "#") {
    return {
      status: "resolved",
      section: "overview",
      runStudioRoute: null,
      mediaRoute: null,
      taskGalleryRoute: null,
      worldRoute: null,
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

  if (query !== "" && !["media", "runs", "threads", "reports", "tasks", "world", "projects"].includes(section.id)) {
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
      mediaRoute: null,
      taskGalleryRoute: null,
      worldRoute: null,
      resourceId: null,
    };
  }

  if (section.id === "media") {
    const result = resolveMediaRoute(query);

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
      runStudioRoute: null,
      mediaRoute: result.route,
      taskGalleryRoute: null,
      worldRoute: null,
      resourceId: null,
    };
  }

  if (section.id === "tasks") {
    const result = resolveTaskGalleryRoute(query);
    if (result.status === "invalid") {
      return { status: "invalid", hash, message: result.message };
    }
    return {
      status: "resolved",
      section: section.id,
      runStudioRoute: null,
      mediaRoute: null,
      taskGalleryRoute: result.route,
      worldRoute: null,
      resourceId: null,
    };
  }

  if (section.id === "world") {
    const result = resolveWorldRoute(query);
    if (result.status === "invalid") {
      return { status: "invalid", hash, message: result.message };
    }
    return {
      status: "resolved",
      section: section.id,
      runStudioRoute: null,
      mediaRoute: null,
      taskGalleryRoute: null,
      worldRoute: result.route,
      resourceId: null,
    };
  }

  if (section.id === "projects") {
    const result = resolveResearchProjectRoute(query);
    if (result.status === "invalid") {
      return { status: "invalid", hash, message: result.message };
    }
    return {
      status: "resolved",
      section: section.id,
      runStudioRoute: null,
      mediaRoute: null,
      taskGalleryRoute: null,
      worldRoute: null,
      resourceId: null,
      researchProjectRoute: result.route,
    };
  }

  if (section.id === "reports") {
    const result = resolveReportWorkspaceRoute(query);
    if (result.status === "invalid") {
      return { status: "invalid", hash, message: result.message };
    }
    return {
      status: "resolved",
      section: section.id,
      runStudioRoute: null,
      mediaRoute: null,
      taskGalleryRoute: null,
      worldRoute: null,
      resourceId: null,
      reportWorkspaceRoute: result.route,
    };
  }

  if (section.id === "threads") {
    const parameters = new URLSearchParams(query);
    const expectedName = "thread_id";
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
      mediaRoute: null,
      taskGalleryRoute: null,
      worldRoute: null,
      resourceId,
    };
  }

  return {
    status: "resolved",
    section: section.id,
    runStudioRoute: null,
    mediaRoute: null,
    taskGalleryRoute: null,
    worldRoute: null,
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
    <div className="workspace route-error-page">
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
            <p>回到态势总览后，可从主导航重新进入需要的工作区。</p>
            <a className="button button-primary" href={createSectionHref("overview")}>返回态势总览</a>
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
  const updateMediaRoute = useCallback((nextRoute: MediaRoute): void => {
    window.location.hash = createMediaHash(nextRoute);
  }, []);
  const updateTaskGalleryRoute = useCallback((nextRoute: TaskGalleryRoute): void => {
    window.location.hash = createTaskGalleryHash(nextRoute);
  }, []);
  const updateWorldRoute = useCallback((nextRoute: WorldRoute): void => {
    window.location.hash = createWorldHash(nextRoute);
  }, []);
  const updateResearchProjectRoute = useCallback((nextRoute: ResearchProjectRoute): void => {
    window.location.hash = createResearchProjectHash(nextRoute);
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
      <Suspense fallback={<PageLoadingFallback />}>
        {renderActivePage(
          activeSection,
          navigate,
          route.runStudioRoute,
          updateRunStudioRoute,
          route.mediaRoute,
          updateMediaRoute,
          route.taskGalleryRoute,
          updateTaskGalleryRoute,
          route.worldRoute,
          updateWorldRoute,
          route.researchProjectRoute ?? null,
          updateResearchProjectRoute,
          route.resourceId,
          route.reportWorkspaceRoute ?? null,
        )}
      </Suspense>
    </AppShell>
  );
}
