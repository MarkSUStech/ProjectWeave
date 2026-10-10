export function Spinner({ label = '加载中…' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-12 text-sm text-ink-dim" role="status">
      <span className="size-4 animate-spin rounded-full border-2 border-edge border-t-accent" />
      {label}
    </div>
  )
}

export function ErrorBanner({
  message,
  onRetry,
}: {
  message: string
  onRetry?: () => void
}) {
  return (
    <div
      role="alert"
      className="flex flex-col items-start justify-between gap-2 rounded-md border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-ink sm:flex-row sm:items-center"
    >
      <span>
        <span className="font-medium text-danger">加载失败：</span>
        {message}
      </span>
      {onRetry && (
        <button
          onClick={onRetry}
          className="rounded border border-edge px-2.5 py-1 text-xs text-ink-dim hover:text-ink"
        >
          重试
        </button>
      )}
    </div>
  )
}
