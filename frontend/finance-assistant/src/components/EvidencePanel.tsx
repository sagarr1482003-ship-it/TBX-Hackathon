import { ArrowsClockwise, DownloadSimple, FileMagnifyingGlass, Receipt, SidebarSimple } from '@phosphor-icons/react'
import type { QueryResult } from '../lib/types'
import { ConfidenceBadge } from './ConfidenceBadge'
import { BreakdownTable } from './BreakdownTable'
import { AnomalyCallout } from './AnomalyCallout'
import { ReasoningTrace } from './ReasoningTrace'
import { ChartView } from './ChartView'
import { MetricStrip } from './MetricStrip'
import { formatUSD } from '../lib/format'
import { downloadCsv } from '../lib/csv'

function EmptyEvidence() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-8 text-center">
      <div className="flex h-11 w-11 items-center justify-center rounded-full bg-sunken dark:bg-sunken-dark">
        <FileMagnifyingGlass size={20} className="text-ink-faint dark:text-ink-faint-dark" />
      </div>
      <p className="max-w-[24ch] text-sm text-ink-faint dark:text-ink-faint-dark">
        Ask a question and the records behind the answer will show up here.
      </p>
    </div>
  )
}

export function EvidencePanel({ result, onCollapse }: { result?: QueryResult; onCollapse?: () => void }) {
  if (!result) {
    return (
      <div className="flex h-full flex-col">
        <PanelHeader onCollapse={onCollapse} />
        <EmptyEvidence />
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <PanelHeader onCollapse={onCollapse} />
      <div className="flex-1 space-y-5 overflow-y-auto px-5 py-5 pb-24">
        <div className="flex flex-wrap items-center gap-2">
          <ConfidenceBadge confidence={result.confidence} />
        </div>
        <p className="text-xs leading-relaxed text-ink-muted dark:text-ink-muted-dark">{result.confidenceNote}</p>

        {result.chart && (
          <section>
            <h3 className="mb-2 text-xs font-medium text-ink-faint dark:text-ink-faint-dark">Visualisation</h3>
            <div className="rounded-[10px] border border-line bg-paper p-4 dark:border-line-dark dark:bg-paper-dark">
              <MetricStrip result={result} />
              <div className="mt-3">
                <ChartView chart={result.chart} dark={document.documentElement.classList.contains('dark')} />
              </div>
            </div>
          </section>
        )}

        {result.filters.length > 0 && (
          <section>
            <h3 className="mb-2 text-xs font-medium text-ink-faint dark:text-ink-faint-dark">What was parsed from your question</h3>
            <div className="flex flex-wrap gap-1.5">
              {result.filters.map((f) => (
                <span
                  key={f.label}
                  className="rounded-full border border-line bg-surface px-2.5 py-1 text-xs text-ink dark:border-line-dark dark:bg-surface-dark dark:text-ink-dark"
                >
                  <span className="text-ink-faint dark:text-ink-faint-dark">{f.label}: </span>
                  {f.value}
                </span>
              ))}
            </div>
          </section>
        )}

        {result.steps.length > 0 && (
          <section>
            <h3 className="mb-3 text-xs font-medium text-ink-faint dark:text-ink-faint-dark">How the agent got here</h3>
            <ReasoningTrace steps={result.steps} />
          </section>
        )}

        {result.anomaly?.text && <AnomalyCallout text={result.anomaly.text} />}

        {result.groupBy && result.groupBy.length > 0 && (
          <section>
            <h3 className="mb-2 text-xs font-medium text-ink-faint dark:text-ink-faint-dark">Breakdown</h3>
            <div className="divide-y divide-line rounded-[10px] border border-line dark:divide-line-dark dark:border-line-dark">
              {result.groupBy.map((g) => (
                <div key={g.label} className="flex items-center justify-between px-3.5 py-2.5 text-sm">
                  <span className="text-ink dark:text-ink-dark">
                    {g.label} <span className="text-ink-faint dark:text-ink-faint-dark">· {g.count}</span>
                  </span>
                  <span className="font-mono text-ink dark:text-ink-dark">{formatUSD(g.value)}</span>
                </div>
              ))}
            </div>
          </section>
        )}

        {result.records.length > 0 && (
          <section>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-xs font-medium text-ink-faint dark:text-ink-faint-dark">
                Source records ({result.records.length})
              </h3>
              <button
                onClick={() => downloadCsv(`verity-export-${result.id}.csv`, result.records)}
                className="flex items-center gap-1.5 rounded-[10px] border border-line px-2.5 py-1.5 text-xs font-medium text-ink-muted transition-colors hover:bg-sunken hover:text-ink dark:border-line-dark dark:text-ink-muted-dark dark:hover:bg-sunken-dark dark:hover:text-ink-dark"
              >
                <DownloadSimple size={13} />
                Export CSV
              </button>
            </div>
            <BreakdownTable records={result.records} />
          </section>
        )}

        <p className="flex items-center gap-1.5 pt-1 font-mono text-[11px] text-ink-faint dark:text-ink-faint-dark">
          <ArrowsClockwise size={12} />
          {result.sourceRef}
        </p>
      </div>
    </div>
  )
}

function PanelHeader({ onCollapse }: { onCollapse?: () => void }) {
  return (
    <div className="flex h-12 shrink-0 items-center gap-2 border-b border-line px-5 dark:border-line-dark">
      <Receipt size={15} className="text-ink-muted dark:text-ink-muted-dark" />
      <span className="flex-1 text-sm font-medium text-ink dark:text-ink-dark">Evidence</span>
      {onCollapse && (
        <button
          onClick={onCollapse}
          aria-label="Hide evidence panel"
          title="Hide evidence panel"
          className="hidden shrink-0 items-center justify-center rounded-[8px] p-1.5 text-ink-faint hover:bg-sunken hover:text-ink dark:text-ink-faint-dark dark:hover:bg-sunken-dark dark:hover:text-ink-dark lg:flex"
        >
          <SidebarSimple size={16} className="scale-x-[-1]" />
        </button>
      )}
    </div>
  )
}
