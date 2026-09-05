import type { Transaction } from './types'
import { VENDORS } from '../data/vendors'
import { ACCOUNTS } from '../data/accounts'

const vendorName = (id: string) => VENDORS.find((v) => v.id === id)?.name ?? id
const accountName = (code: string) => ACCOUNTS.find((a) => a.code === code)?.name ?? code

export function downloadCsv(filename: string, records: Transaction[]) {
  const header = ['Transaction ID', 'Date', 'Vendor', 'Account', 'Description', 'Amount', 'Status']
  const lines = records.map((r) =>
    [r.id, r.date, vendorName(r.vendorId), accountName(r.accountCode), r.description, r.amount.toFixed(2), r.status]
      .map((cell) => `"${String(cell).replace(/"/g, '""')}"`)
      .join(','),
  )
  const csv = [header.join(','), ...lines].join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}
