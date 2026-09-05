import { useId, useState } from 'react'
import { Calculator, CaretRight, Funnel, MagnifyingGlass, ShieldWarning, Warning } from '@phosphor-icons/react'
import type { TraceDetail, TraceKind, TraceStep, TraceTable } from '../lib/types'

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

/** Rows rendered inline before the "showing N of M" caption kicks in. */
const MAX_TABLE_ROWS = 20

const LABEL_CLASS = 'text-sm leading-relaxed text-ink-muted dark:text-ink-muted-dark'

function formatDuration(ms: number): string {
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`
}

function isExpandable(step: TraceStep): boolean {
  return Boolean(step.details?.length || step.table)
}

function DurationBadge({ ms }: { ms: number }) {
  return (
    <span className="shrink-0 font-mono text-[10px] text-ink-faint dark:text-ink-faint-dark">
      {formatDuration(ms)}
    </span>
  )
}

function DetailBlock({ detail }: { detail: TraceDetail }) {
  const mono = detail.format === 'sql' || detail.format === 'json'
  return (
    <div className="space-y-1">
      <p className="text-[10px] font-medium text-ink-faint dark:text-ink-faint-dark">{detail.label}</p>
      {mono ? (
        <pre className="overflow-x-auto rounded-[8px] border border-line bg-sunken px-3 py-2 font-mono text-[11px] leading-relaxed whitespace-pre-wrap break-words text-ink dark:border-line-dark dark:bg-sunken-dark dark:text-ink-dark">
          {detail.value}
        </pre>
      ) : (
        <p className="text-xs leading-relaxed whitespace-pre-wrap text-ink-muted dark:text-ink-muted-dark">
          {detail.value}
        </p>
      )}
    </div>
  )
}

function DetailTable({ table }: { table: TraceTable }) {
  const visible = table.rows.slice(0, MAX_TABLE_ROWS)
  const total = table.totalRowCount ?? table.rows.length
  const truncated = table.rows.length > MAX_TABLE_ROWS || total > table.rows.length

  return (
    <div className="space-y-1">
      <p className="text-[10px] font-medium text-ink-faint dark:text-ink-faint-dark">Result rows</p>
      <div className="max-h-64 overflow-auto rounded-[8px] border border-line dark:border-line-dark">
        <table className="w-full border-collapse font-mono text-[11px]">
          <thead>
            <tr className="bg-sunken dark:bg-sunken-dark">
              {table.columns.map((col) => (
                <th
                  key={col}
                  scope="col"
                  className="border-b border-line px-2.5 py-1.5 text-left font-medium whitespace-nowrap text-ink-faint dark:border-line-dark dark:text-ink-faint-dark"
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((row, i) => (
              <tr key={i} className="border-b border-line last:border-0 dark:border-line-dark">
                {table.columns.map((col) => (
                  <td
                    key={col}
                    className={`px-2.5 py-1.5 whitespace-nowrap text-ink dark:text-ink-dark ${
                      typeof row[col] === 'number' ? 'text-right' : 'text-left'
                    }`}
                  >
                    {String(row[col] ?? '')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {truncated && (
        <p className="text-[10px] text-ink-faint dark:text-ink-faint-dark">
          Showing {Math.min(MAX_TABLE_ROWS, table.rows.length)} of {total} rows
        </p>
      )}
    </div>
  )
}

export function ReasoningTrace({ steps }: { steps: TraceStep[] }) {
  const idPrefix = useId()
  const [open, setOpen] = useState<Set<number>>(() => new Set())

  if (!steps.length) return null

  const toggle = (index: number) =>
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(index)) next.delete(index)
      else next.add(index)
      return next
    })

  return (
    <ol className="space-y-0">
      {steps.map((s, i) => {
        const meta = KIND_META[s.kind]
        const Icon = meta.icon
        const isLast = i === steps.length - 1
        const expandable = isExpandable(s)
        const isOpen = expandable && open.has(i)
        const panelId = `${idPrefix}-trace-panel-${i}`

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

            <div className="min-w-0 flex-1">
              {expandable ? (
                <button
                  type="button"
                  onClick={() => toggle(i)}
                  aria-expanded={isOpen}
                  aria-controls={panelId}
                  className={`flex w-full items-start gap-1.5 rounded-[6px] pt-1 text-left transition-colors hover:text-ink focus-visible:ring-2 focus-visible:ring-accent/50 focus-visible:outline-none dark:hover:text-ink-dark dark:focus-visible:ring-accent-dark/50 ${LABEL_CLASS}`}
                >
                  <CaretRight
                    size={11}
                    weight="bold"
                    aria-hidden
                    className={`mt-[5px] shrink-0 transition-transform ${isOpen ? 'rotate-90' : ''}`}
                  />
                  <span className="min-w-0 flex-1">{s.label}</span>
                  {s.durationMs != null && (
                    <span className="mt-[5px]">
                      <DurationBadge ms={s.durationMs} />
                    </span>
                  )}
                </button>
              ) : (
                <div className="flex items-start gap-1.5 pt-1">
                  <p className={`min-w-0 flex-1 ${LABEL_CLASS}`}>{s.label}</p>
                  {s.durationMs != null && (
                    <span className="mt-[5px]">
                      <DurationBadge ms={s.durationMs} />
                    </span>
                  )}
                </div>
              )}

              {expandable && (
                <div id={panelId} hidden={!isOpen} className="space-y-3 pt-2">
                  {s.details?.map((d, di) => (
                    <DetailBlock key={`${d.label}-${di}`} detail={d} />
                  ))}
                  {s.table && <DetailTable table={s.table} />}
                </div>
              )}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
