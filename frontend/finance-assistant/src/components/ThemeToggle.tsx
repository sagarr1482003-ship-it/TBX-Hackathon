import { MoonStars, Sun } from '@phosphor-icons/react'

export function ThemeToggle({ dark, onToggle }: { dark: boolean; onToggle: () => void }) {
  return (
    <button
      onClick={onToggle}
      aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'}
      className="flex h-9 w-9 items-center justify-center rounded-[10px] border border-line text-ink-muted transition-colors hover:bg-sunken hover:text-ink dark:border-line-dark dark:text-ink-muted-dark dark:hover:bg-sunken-dark dark:hover:text-ink-dark"
    >
      {dark ? <Sun size={17} weight="regular" /> : <MoonStars size={17} weight="regular" />}
    </button>
  )
}
