import { Warning } from '@phosphor-icons/react'

export function AnomalyCallout({ text }: { text: string }) {
  return (
    <div className="flex gap-2.5 rounded-[10px] border border-amber/25 bg-amber-soft px-3.5 py-3 text-sm text-ink dark:border-amber-dark/25 dark:bg-amber-soft-dark dark:text-ink-dark">
      <Warning size={17} weight="fill" className="mt-0.5 shrink-0 text-amber dark:text-amber-dark" />
      <p className="leading-relaxed">
        <span className="font-medium text-amber dark:text-amber-dark">Worth a look. </span>
        {text}
      </p>
    </div>
  )
}
