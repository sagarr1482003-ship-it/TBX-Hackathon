import { Cpu, List } from '@phosphor-icons/react'
import { COMPANY_NAME } from '../data/vendors'
import { ThemeToggle } from './ThemeToggle'

export function Header({
  dark,
  onToggleTheme,
  onMenuClick,
}: {
  dark: boolean
  onToggleTheme: () => void
  onMenuClick: () => void
}) {
  return (
    <header className="flex h-16 shrink-0 items-center justify-between border-b border-line px-3 dark:border-line-dark sm:px-6">
      <div className="flex items-center gap-1 sm:gap-3">
        <button
          onClick={onMenuClick}
          aria-label="Toggle chat history"
          className="flex h-9 w-9 items-center justify-center rounded-[10px] text-ink-muted hover:bg-sunken hover:text-ink dark:text-ink-muted-dark dark:hover:bg-sunken-dark dark:hover:text-ink-dark md:hidden"
        >
          <List size={18} />
        </button>
        <div className="flex h-8 w-8 items-center justify-center rounded-[10px] bg-ink dark:bg-ink-dark">
          <svg width="16" height="16" viewBox="0 0 32 32" fill="none">
            <path d="M9 16.5L14 21.5L23 11" stroke="var(--color-accent-dark)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
        <div className="leading-tight">
          <div className="font-semibold tracking-tight text-ink dark:text-ink-dark">Verity</div>
          <div className="hidden text-xs text-ink-faint dark:text-ink-faint-dark sm:block">{COMPANY_NAME}</div>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <div className="hidden items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1.5 text-xs text-ink-muted dark:border-line-dark dark:bg-surface-dark dark:text-ink-muted-dark md:flex">
          <Cpu size={14} className="text-accent dark:text-accent-dark" />
          <span className="font-mono">Phi-3.5-mini · 3.8B</span>
        </div>
        <ThemeToggle dark={dark} onToggle={onToggleTheme} />
      </div>
    </header>
  )
}
