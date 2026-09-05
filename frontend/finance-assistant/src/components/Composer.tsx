import { useState } from 'react'
import { ArrowUp } from '@phosphor-icons/react'

const SUGGESTIONS = [
  'Which transactions are still unreconciled?',
  'How much did we spend on logistics this month?',
  'Any unusual vendor payments recently?',
  "What's our projected profit for next quarter?",
]

export function Composer({ onSubmit, disabled }: { onSubmit: (text: string) => void; disabled: boolean }) {
  const [value, setValue] = useState('')

  function submit() {
    const trimmed = value.trim()
    if (!trimmed || disabled) return
    onSubmit(trimmed)
    setValue('')
  }

  return (
    <div className="shrink-0 border-t border-line px-4 py-3.5 dark:border-line-dark sm:px-5">
      <div className="mb-2.5 flex flex-wrap gap-1.5">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            onClick={() => onSubmit(s)}
            disabled={disabled}
            className="rounded-full border border-line px-3 py-1.5 text-xs text-ink-muted transition-colors hover:border-ink-faint/50 hover:text-ink disabled:opacity-50 dark:border-line-dark dark:text-ink-muted-dark dark:hover:text-ink-dark"
          >
            {s}
          </button>
        ))}
      </div>
      <div className="flex items-end gap-2 rounded-[10px] border border-line bg-surface px-3 py-2 focus-within:border-accent/50 dark:border-line-dark dark:bg-surface-dark dark:focus-within:border-accent-dark/50">
        <textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              submit()
            }
          }}
          rows={1}
          placeholder="Ask about spend, payouts, or reconciliation status..."
          className="max-h-28 flex-1 resize-none bg-transparent py-1 text-sm text-ink placeholder:text-ink-faint focus:outline-none dark:text-ink-dark dark:placeholder:text-ink-faint-dark"
        />
        <button
          onClick={submit}
          disabled={disabled || !value.trim()}
          aria-label="Send question"
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[8px] bg-ink text-paper transition-opacity disabled:opacity-30 dark:bg-ink-dark dark:text-paper-dark"
        >
          <ArrowUp size={15} weight="bold" />
        </button>
      </div>
    </div>
  )
}
