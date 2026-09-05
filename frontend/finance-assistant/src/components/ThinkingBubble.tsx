export function ThinkingBubble({ label }: { label?: string }) {
  return (
    <div className="msg-in max-w-[88%] rounded-[10px] border border-line bg-surface px-4 py-3.5 dark:border-line-dark dark:bg-surface-dark">
      {label && (
        <p className="mb-2.5 text-xs text-ink-faint dark:text-ink-faint-dark">{label}…</p>
      )}
      <div className="space-y-2">
        <div className="h-3 w-3/4 animate-pulse rounded bg-sunken dark:bg-sunken-dark" />
        <div className="h-3 w-2/5 animate-pulse rounded bg-sunken dark:bg-sunken-dark" />
      </div>
    </div>
  )
}
