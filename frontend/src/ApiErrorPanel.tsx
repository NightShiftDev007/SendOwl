export interface ApiErrorPanelProps {
  readonly title: string;
  readonly error: Error;
  readonly isRetrying: boolean;
  readonly onRetry: () => void;
}

export function ApiErrorPanel({
  title,
  error,
  isRetrying,
  onRetry,
}: ApiErrorPanelProps): JSX.Element {
  return (
    <div className="api-error-panel" role="alert">
      <div>
        <strong>{title}</strong>
        <p>{error.message}</p>
        <small>请检查 V2 API 反向代理、后端接口响应和服务日志。</small>
      </div>
      <button
        className="button button-secondary"
        type="button"
        disabled={isRetrying}
        aria-busy={isRetrying}
        onClick={onRetry}
      >
        {isRetrying ? "正在重连…" : "重新连接"}
      </button>
    </div>
  );
}
