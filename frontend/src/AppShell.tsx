import { useEffect, useRef, type ReactNode } from "react";

import type { NavigationItem, SectionId } from "./domain";
import "./appShell.css";

export interface AppShellProps {
  readonly activeSection: SectionId;
  readonly activeItem: NavigationItem;
  readonly navigation: readonly NavigationItem[];
  readonly children: ReactNode;
  readonly createSectionHref: (sectionId: SectionId) => string;
}

interface PrimaryDestination {
  readonly id: "situation" | "workspace" | "runs";
  readonly label: string;
  readonly shortLabel: string;
  readonly hrefSection: SectionId;
  readonly sections: readonly SectionId[];
}

const PRIMARY_DESTINATIONS: readonly PrimaryDestination[] = [
  {
    id: "situation",
    label: "态势",
    shortLabel: "态势",
    hrefSection: "overview",
    sections: ["overview"],
  },
  {
    id: "workspace",
    label: "Decision Workspace",
    shortLabel: "Workspace",
    hrefSection: "media",
    sections: ["media", "companies", "world", "decisions"],
  },
  {
    id: "runs",
    label: "Run Studio",
    shortLabel: "Run Studio",
    hrefSection: "runs",
    sections: ["runs", "reports"],
  },
];

const WORKSPACE_STAGE_IDS = [
  "media",
  "companies",
  "world",
  "decisions",
] as const satisfies readonly SectionId[];

const WORKSPACE_STAGE_LABELS: Readonly<Record<(typeof WORKSPACE_STAGE_IDS)[number], string>> = {
  media: "媒体证据",
  companies: "企业核验",
  world: "冻结现实",
  decisions: "决策实验",
};

function requireNavigationItem(
  navigation: readonly NavigationItem[],
  sectionId: SectionId,
): NavigationItem {
  const item = navigation.find((candidate) => candidate.id === sectionId);

  if (item === undefined) {
    throw new Error(`App shell navigation is missing section: ${sectionId}`);
  }

  return item;
}

function includesSection(
  sections: readonly SectionId[],
  activeSection: SectionId,
): boolean {
  return sections.includes(activeSection);
}

export function AppShell({
  activeSection,
  activeItem,
  navigation,
  children,
  createSectionHref,
}: AppShellProps): JSX.Element {
  const mainContentRef = useRef<HTMLElement>(null);
  const previousSectionRef = useRef<SectionId>(activeSection);
  const isDecisionWorkspace = includesSection(WORKSPACE_STAGE_IDS, activeSection);
  const isRunWorkspace = activeSection === "runs" || activeSection === "reports";

  useEffect(() => {
    if (previousSectionRef.current === activeSection) {
      return;
    }

    previousSectionRef.current = activeSection;
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
    mainContentRef.current?.focus({ preventScroll: true });
  }, [activeSection]);

  return (
    <div className="product-shell" data-section={activeSection}>
      <a className="product-skip-link" href="#product-main">
        跳到主要内容
      </a>

      <header className="product-chrome">
        <div className="product-topbar">
          <a
            className="product-brand"
            href={createSectionHref("overview")}
            aria-label="SandOwl Decision Intelligence，返回态势页"
          >
            <span className="product-brand-mark" aria-hidden="true">
              <span />
              <span />
            </span>
            <span className="product-brand-copy">
              <strong>SandOwl</strong>
              <small>Decision Intelligence</small>
            </span>
          </a>

          <nav className="product-primary-nav" aria-label="产品任务面">
            {PRIMARY_DESTINATIONS.map((destination, index) => {
              const isActive = includesSection(destination.sections, activeSection);

              return (
                <a
                  key={destination.id}
                  className="product-primary-link"
                  href={createSectionHref(destination.hrefSection)}
                  data-active={isActive}
                  aria-current={isActive ? "page" : undefined}
                >
                  <span className="product-primary-index" aria-hidden="true">
                    0{index + 1}
                  </span>
                  <span className="product-primary-label">{destination.label}</span>
                  <span className="product-primary-label-short">{destination.shortLabel}</span>
                </a>
              );
            })}
          </nav>

          <div className="product-context" aria-label="当前任务上下文">
            <span>{activeItem.description}</span>
            <strong>{activeItem.label}</strong>
          </div>
        </div>

        {isDecisionWorkspace ? (
          <nav className="product-task-rail" aria-label="Decision Workspace 任务阶段">
            <ol>
              {WORKSPACE_STAGE_IDS.map((sectionId, index) => {
                const item = requireNavigationItem(navigation, sectionId);
                const isActive = sectionId === activeSection;

                return (
                  <li key={sectionId}>
                    <a
                      href={createSectionHref(sectionId)}
                      data-active={isActive}
                      aria-current={isActive ? "step" : undefined}
                      title={item.description}
                    >
                      <span aria-hidden="true">{index + 1}</span>
                      <strong>{WORKSPACE_STAGE_LABELS[sectionId]}</strong>
                    </a>
                  </li>
                );
              })}
            </ol>
          </nav>
        ) : null}

        {isRunWorkspace ? (
          <div className="product-run-rail" aria-label="Run Studio 阶段">
            <a
              href={createSectionHref("runs")}
              data-active={activeSection === "runs"}
              aria-current={activeSection === "runs" ? "page" : undefined}
            >
              运行控制
            </a>
            <span aria-disabled="true" data-active={activeSection === "reports"}>
              决策报告
              <small>待真实 API</small>
            </span>
          </div>
        ) : null}
      </header>

      <main
        id="product-main"
        ref={mainContentRef}
        className="product-main"
        data-section={activeSection}
        tabIndex={-1}
        aria-label={`${activeItem.label}工作区`}
      >
        {children}
      </main>
    </div>
  );
}
