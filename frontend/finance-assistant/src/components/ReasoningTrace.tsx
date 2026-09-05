import { Calculator, Funnel, MagnifyingGlass, ShieldWarning, Warning } from '@phosphor-icons/react'
import type { TraceKind, TraceStep } from '../lib/types'

const KIND_META: Record<TraceKind, { icon: typeof Calculator; tone: 'neutral' | 'flag' | 'guardrail' }> = {
  parse: { icon: MagnifyingGlass, tone: 'neutral' },
  filter: { icon: Funnel, tone: 'neutral' },
  compute: { icon: Calculator, tone: 'neutral' },
  flag: { icon: Warning, tone: 'flag' },
  guardrail: { icon: ShieldWarning, tone: 'guardrail' },
}

const TONE_CLASSES: Record<string, string> = {
  neutral: 'bg-sunken text-ink-muted dark:bg-sunken-dark dark:text-ink-muted-dark',
  flag: 'bg-amber-soft text-amber dark:bg-amber-soft-dark dark:text-amber-dark',
  guardrail: 'bg-brick-soft text-brick dark:bg-brick-soft-dark dark:text-brick-dark',
}

export function ReasoningTrace({ steps }: { steps: TraceStep[] }) {
  if (!steps.length) return null

  return (
    <ol className="space-y-0">
      {steps.map((s, i) => {
        const meta = KIND_META[s.kind]
        const Icon = meta.icon
        const isLast = i === steps.length - 1
        return (
          <li key={i} className="relative flex gap-3 pb-4 last:pb-0">
            {!isLast && (
              <span className="absolute left-[13px] top-[26px] h-[calc(100%-22px)] w-px bg-line dark:bg-line-dark" aria-hidden />
            )}
            <span
              className={`relative z-10 flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-full ${TONE_CLASSES[meta.tone]}`}
            >
              <Icon size={13} weight="bold" />
            </span>
            <p className="pt-1 text-sm leading-relaxed text-ink-muted dark:text-ink-muted-dark">{s.label}</p>
          </li>
        )
      })}
    </ol>
  )
}
