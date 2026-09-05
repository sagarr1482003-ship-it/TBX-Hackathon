import { CheckCircle, WarningCircle, Question } from '@phosphor-icons/react'
import type { QueryResult } from '../lib/types'

const STYLES: Record<QueryResult['confidence'], { label: string; icon: typeof CheckCircle; className: string }> = {
  high: {
    label: 'High confidence',
    icon: CheckCircle,
    className: 'bg-accent-soft text-accent-strong dark:bg-accent-soft-dark dark:text-accent-dark',
  },
  medium: {
    label: 'Medium confidence',
    icon: WarningCircle,
    className: 'bg-amber-soft text-amber dark:bg-amber-soft-dark dark:text-amber-dark',
  },
  low: {
    label: 'Low confidence',
    icon: Question,
    className: 'bg-brick-soft text-brick dark:bg-brick-soft-dark dark:text-brick-dark',
  },
}

export function ConfidenceBadge({ confidence }: { confidence: QueryResult['confidence'] }) {
  const s = STYLES[confidence]
  const Icon = s.icon
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${s.className}`}>
      <Icon size={13} weight="fill" />
      {s.label}
    </span>
  )
}
