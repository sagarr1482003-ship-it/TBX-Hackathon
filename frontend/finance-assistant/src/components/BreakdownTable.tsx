import type { Transaction } from '../lib/types'
import { VENDORS } from '../data/vendors'
import { ACCOUNTS } from '../data/accounts'
import { formatDate, formatUSD } from '../lib/format'

const vendorName = (id: string) => VENDORS.find((v) => v.id === id)?.name ?? id
const accountName = (code: string) => ACCOUNTS.find((a) => a.code === code)?.name ?? code

export function BreakdownTable({ records }: { records: Transaction[] }) {
  if (!records.length) return null

  return (
    <div className="overflow-x-auto rounded-[10px] border border-line dark:border-line-dark">
      <table className="w-full min-w-[560px] border-collapse text-sm">
        <thead>
          <tr className="border-b border-line bg-sunken text-left text-xs uppercase tracking-wide text-ink-faint dark:border-line-dark dark:bg-sunken-dark dark:text-ink-faint-dark">
            <th className="px-3 py-2 font-medium">Date</th>
            <th className="px-3 py-2 font-medium">Vendor</th>
            <th className="px-3 py-2 font-medium">Category</th>
            <th className="px-3 py-2 font-medium">Status</th>
            <th className="px-3 py-2 text-right font-medium">Amount</th>
          </tr>
        </thead>
        <tbody>
          {records.map((r) => (
            <tr key={r.id} className="border-b border-line last:border-0 dark:border-line-dark">
              <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-ink-muted dark:text-ink-muted-dark">{formatDate(r.date)}</td>
              <td className="px-3 py-2 text-ink dark:text-ink-dark">{vendorName(r.vendorId)}</td>
              <td className="px-3 py-2 text-ink-muted dark:text-ink-muted-dark">{accountName(r.accountCode)}</td>
              <td className="px-3 py-2">
                <span
                  className={
                    r.status === 'reconciled'
                      ? 'text-accent dark:text-accent-dark'
                      : 'text-amber dark:text-amber-dark'
                  }
                >
                  {r.status === 'reconciled' ? 'Reconciled' : 'Unreconciled'}
                </span>
              </td>
              <td className="whitespace-nowrap px-3 py-2 text-right font-mono text-ink dark:text-ink-dark">{formatUSD(r.amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
