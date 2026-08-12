import { useCallback, useEffect, useState } from "react";

import { AppShell } from "./AppShell";
import { CompanyEvidencePage } from "./CompanyEvidencePage";
import {
  moduleDefinitions,
  navigationItems,
  requireNavigationItem,
  type SectionId,
} from "./domain";
import { MediaPage } from "./MediaPage";
import { ModulePage } from "./ModulePage";
import { OasisPlatformSmokePage } from "./OasisPlatformSmokePage";
import { OverviewPage } from "./OverviewPage";
import { ScenarioPage } from "./ScenarioPage";
import { WorldModelPage } from "./WorldModelPage";

function renderActivePage(
  activeSection: SectionId,
  onNavigate: (sectionId: SectionId) => void,
): JSX.Element {
  if (activeSection === "overview") {
    return <OverviewPage onNavigate={onNavigate} />;
  }

  if (activeSection === "media") {
    return <MediaPage />;
  }

  if (activeSection === "companies") {
    return <CompanyEvidencePage />;
  }

  if (activeSection === "world") {
    return <WorldModelPage />;
  }

  if (activeSection === "decisions") {
    return <ScenarioPage />;
  }

  if (activeSection === "runs") {
    return <OasisPlatformSmokePage />;
  }

  return (
    <ModulePage
      definition={moduleDefinitions[activeSection]}
      navigationItem={requireNavigationItem(activeSection)}
    />
  );
}

function createSectionHref(sectionId: SectionId): string {
  return `#/${sectionId}`;
}

type HashRoute =
  | { readonly status: "resolved"; readonly section: SectionId }
  | { readonly status: "invalid"; readonly hash: string; readonly message: string };

export function resolveSectionFromHash(hash: string): HashRoute {
  if (hash === "" || hash === "#") {
    return { status: "resolved", section: "overview" };
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

  const sectionName = hash.slice(2);
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

  return { status: "resolved", section: section.id };
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
      {renderActivePage(activeSection, navigate)}
    </AppShell>
  );
}
