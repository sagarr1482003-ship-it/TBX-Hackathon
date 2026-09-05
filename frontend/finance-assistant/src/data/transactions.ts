import type { Transaction } from '../lib/types'
import { VENDORS } from './vendors'

// Deterministic PRNG so the demo dataset is stable across reloads.
function mulberry32(seed: number) {
  return function () {
    seed |= 0
    seed = (seed + 0x6d2b79f5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const rand = mulberry32(190426)

const VENDOR_PROFILE: Record<string, { account: string; base: number; spread: number; freq: number }> = {
  v01: { account: '6100', base: 4200, spread: 2600, freq: 5 }, // Meridian Logistics
  v02: { account: '6010', base: 380, spread: 340, freq: 4 }, // Cobalt Office Supply
  v03: { account: '5100', base: 2100, spread: 1500, freq: 4 }, // Anchor Print & Packaging
  v04: { account: '6300', base: 6800, spread: 3200, freq: 2 }, // Sable & Finch Consulting
  v05: { account: '5000', base: 9600, spread: 4800, freq: 4 }, // Redline Steel Supply
  v06: { account: '6200', base: 1450, spread: 300, freq: 3 }, // Northbridge Software
  v07: { account: '6100', base: 3100, spread: 1800, freq: 3 }, // Harlow Freight Co.
  v08: { account: '6300', base: 5200, spread: 2100, freq: 1 }, // Bramwell Legal Group
  v09: { account: '5000', base: 8400, spread: 2600, freq: 3 }, // Ferro Components Ltd.
  v10: { account: '6400', base: 3600, spread: 2200, freq: 2 }, // Aster Marketing Collective
  v11: { account: '6500', base: 2450, spread: 400, freq: 2 }, // Kestrel Facilities Mgmt
  v12: { account: '6200', base: 980, spread: 180, freq: 3 }, // Vantage Cloud Services
}

const DESC_BY_ACCOUNT: Record<string, string[]> = {
  '5000': ['Raw material shipment', 'Coil stock order', 'Alloy batch delivery', 'Bulk steel order'],
  '5100': ['Packaging run', 'Carton stock refill', 'Custom crate order', 'Label & packaging batch'],
  '6010': ['Office supplies restock', 'Printer & consumables', 'Breakroom + office order'],
  '6100': ['Freight - outbound shipment', 'Freight - inbound materials', 'LTL freight run', 'Warehouse transfer'],
  '6200': ['Monthly subscription', 'Platform license renewal', 'Seat license true-up'],
  '6300': ['Advisory retainer', 'Contract review', 'Quarterly advisory services', 'Audit prep support'],
  '6400': ['Campaign production', 'Trade show materials', 'Digital ad management'],
  '6500': ['Facilities maintenance', 'HVAC service contract', 'Janitorial services'],
}

function pick<T>(arr: T[], r: number): T {
  return arr[Math.floor(r * arr.length) % arr.length]
}

function monthDays(year: number, month: number) {
  return new Date(year, month + 1, 0).getDate()
}

const MONTHS: { year: number; month: number; upTo?: number }[] = [
  { year: 2026, month: 5 }, // June
  { year: 2026, month: 6 }, // July
  { year: 2026, month: 7 }, // August
  { year: 2026, month: 8, upTo: 5 }, // September, partial (today is Sep 5)
]

let txCounter = 1
const rows: Transaction[] = []

for (const { year, month, upTo } of MONTHS) {
  const daysInMonth = upTo ?? monthDays(year, month)
  for (const vendor of VENDORS) {
    const profile = VENDOR_PROFILE[vendor.id]
    for (let i = 0; i < profile.freq; i++) {
      const r1 = rand()
      const r2 = rand()
      const r3 = rand()
      const day = Math.max(1, Math.floor(r1 * daysInMonth) + 1)
      const amount = -(profile.base + (r2 - 0.5) * 2 * profile.spread)
      const date = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`
      const desc = pick(DESC_BY_ACCOUNT[profile.account], r3)

      // Recent transactions are more likely to still be open; older ones settle.
      const monthsAgo = (2026 * 12 + 8) - (year * 12 + month)
      const unreconciledChance = monthsAgo === 0 ? 0.55 : monthsAgo === 1 ? 0.18 : 0.05
      const status = rand() < unreconciledChance ? 'unreconciled' : 'reconciled'

      rows.push({
        id: `TXN-${String(txCounter).padStart(4, '0')}`,
        date,
        vendorId: vendor.id,
        accountCode: profile.account,
        description: desc,
        amount: Math.round(amount * 100) / 100,
        status,
        isPayout: true,
      })
      txCounter++
    }
  }
}

// Seeded anomaly: an August payout to Ferro Components far outside its normal range,
// used to demonstrate the anomaly-callout requirement.
rows.push({
  id: `TXN-${String(txCounter).padStart(4, '0')}`,
  date: '2026-08-19',
  vendorId: 'v09',
  accountCode: '5000',
  description: 'Emergency alloy restock - expedited order',
  amount: -34210.5,
  status: 'unreconciled',
  isPayout: true,
})
txCounter++

rows.sort((a, b) => a.date.localeCompare(b.date))

export const TRANSACTIONS: Transaction[] = rows
