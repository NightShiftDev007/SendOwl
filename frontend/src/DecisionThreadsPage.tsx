import { ApiErrorPanel } from "./ApiErrorPanel";
import { useDecisionThreads } from "./useDecisionThreads";
import "./decisionThreads.css";

function shortDigest(value: string | null): string {
  return value === null ? "—" : `${value.slice(0, 10)}…${value.slice(-6)}`;
}

export function createDecisionThreadHash(threadId: string | null): string {
  return threadId === null ? "#/threads" : `#/threads?thread_id=${encodeURIComponent(threadId)}`;
}

export function DecisionThreadsPage({
  selectedThreadId,
  onSelectThread,
}: {
  readonly selectedThreadId: string | null;
  readonly onSelectThread: (threadId: string | null) => void;
}): JSX.Element {
  const threads = useDecisionThreads(selectedThreadId);
  const selectedDetail = threads.detail.data?.id === selectedThreadId
    ? threads.detail.data
    : null;

  return (
    <div className="decision-threads-page">
      <header className="decision-threads-hero">
        <div>
          <span>LEGACY ADC / READ-ONLY</span>
          <h1>历史 Decision Thread 归档</h1>
          <p>这里仅用于恢复旧任务的 World、Scenario、Cohort、Experiment 与报告来源，不再创建任务或追加 Revision。</p>
        </div>
        <aside>
          <strong>兼容边界</strong>
          <p>旧 UUID、内容哈希和修订顺序保持不变。新的研究请从“研究项目”开始。</p>
          <a className="button button-primary" href="#/projects">前往研究项目</a>
        </aside>
      </header>

      <section className="decision-thread-archive-notice" role="note">
        <strong>只读归档</strong>
        <p>创建 Decision Thread、创建草稿和追加上下文版本的入口已经关闭；读取和报告深链继续可用。</p>
      </section>

      <div className="decision-threads-layout">
        <aside className="decision-thread-directory" aria-label="历史决策任务目录">
          <header><strong>历史任务</strong><button type="button" onClick={threads.reload}>刷新</button></header>
          {threads.directory.status === "error" ? <ApiErrorPanel title="无法读取历史决策任务" error={threads.directory.error} isRetrying={false} onRetry={threads.reload} /> : null}
          <ul>
            {threads.directory.data?.items.map((item) => (
              <li key={item.id}>
                <a href={createDecisionThreadHash(item.id)} data-selected={selectedThreadId === item.id} onClick={() => onSelectThread(item.id)}>
                  <strong>{item.title}</strong>
                  <span>{item.latest_revision === null ? "草稿 · 未绑定上下文" : `Revision ${item.latest_revision.version}`}</span>
                  <small>{item.decision_question}</small>
                </a>
              </li>
            ))}
          </ul>
        </aside>

        <section className="decision-thread-stage">
          {selectedThreadId === null ? (
            <div className="decision-thread-empty"><strong>选择一条历史任务</strong><p>系统不会自动打开第一条记录，避免把旧 ADC 上下文误认为当前研究项目。</p></div>
          ) : selectedDetail === null ? (
            threads.detail.status === "error"
              ? <ApiErrorPanel title="无法读取历史决策任务" error={threads.detail.error} isRetrying={false} onRetry={threads.reload} />
              : <p role="status">正在读取历史决策任务…</p>
          ) : (
            <>
              <header>
                <span>ARCHIVED / IMMUTABLE</span><h3>{selectedDetail.title}</h3><p>{selectedDetail.decision_question}</p>
                {selectedDetail.latest_revision?.semantic_experiment_id === null || selectedDetail.latest_revision?.semantic_experiment_id === undefined ? null : (
                  <a className="button button-primary decision-thread-current-report" href={`#/reports?experiment_id=${encodeURIComponent(selectedDetail.latest_revision.semantic_experiment_id)}`}>查看历史报告 →</a>
                )}
              </header>
              {selectedDetail.revisions.length === 0 ? (
                <div className="decision-thread-empty"><strong>历史草稿没有封存 Revision</strong><p>只保留原始标题与问题；归档不会补造 Evidence、Scenario 或实验资源。</p></div>
              ) : (
                <ol className="decision-revision-timeline">
                  {[...selectedDetail.revisions].reverse().map((revision) => (
                    <li key={revision.id}>
                      <header><strong>Revision {revision.version}</strong><time dateTime={revision.created_at}>{new Date(revision.created_at).toLocaleString("zh-CN")}</time></header>
                      <dl>
                        <div><dt>World Snapshot</dt><dd><code>{shortDigest(revision.snapshot_sha256)}</code></dd></div>
                        <div><dt>Scenario</dt><dd><code>{shortDigest(revision.scenario_sha256)}</code></dd></div>
                        <div><dt>Cohort</dt><dd><code>{shortDigest(revision.cohort_sha256)}</code></dd></div>
                        <div><dt>Experiment / Report</dt><dd><code>{shortDigest(revision.experiment_sha256)}</code>{revision.semantic_experiment_id === null ? null : <a href={`#/reports?experiment_id=${encodeURIComponent(revision.semantic_experiment_id)}`}>打开历史报告 →</a>}</dd></div>
                      </dl>
                    </li>
                  ))}
                </ol>
              )}
            </>
          )}
        </section>

        <aside className="decision-thread-context">
          <strong>归档上下文</strong>
          {selectedDetail === null ? <p>选中历史任务后显示最后一个不可变 Revision。</p> : selectedDetail.latest_revision === null ? (
            <><p>该草稿从未绑定 Evidence、Scenario 或实验资源。</p><span className="decision-thread-draft-badge">DRAFT</span></>
          ) : (
            <dl>
              <div><dt>版本</dt><dd>{selectedDetail.latest_revision.version}</dd></div>
              <div><dt>World</dt><dd>{shortDigest(selectedDetail.latest_revision.snapshot_sha256)}</dd></div>
              <div><dt>Scenario</dt><dd>{shortDigest(selectedDetail.latest_revision.scenario_sha256)}</dd></div>
              <div><dt>Cohort</dt><dd>{shortDigest(selectedDetail.latest_revision.cohort_sha256)}</dd></div>
              <div><dt>Experiment</dt><dd>{shortDigest(selectedDetail.latest_revision.experiment_sha256)}</dd></div>
            </dl>
          )}
        </aside>
      </div>
    </div>
  );
}
