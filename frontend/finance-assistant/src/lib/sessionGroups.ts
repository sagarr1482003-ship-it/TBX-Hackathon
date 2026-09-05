import type { ChatSession } from './types'

export function groupSessions(sessions: ChatSession[]) {
  const now = Date.now()
  const startOfToday = new Date(now)
  startOfToday.setHours(0, 0, 0, 0)
  const todayMs = startOfToday.getTime()
  const dayMs = 86_400_000

  const buckets: { label: string; sessions: ChatSession[] }[] = [
    { label: 'Today', sessions: [] },
    { label: 'Yesterday', sessions: [] },
    { label: 'Previous 7 days', sessions: [] },
    { label: 'Older', sessions: [] },
  ]

  const sorted = [...sessions].sort((a, b) => b.createdAt - a.createdAt)

  for (const s of sorted) {
    const age = todayMs - new Date(s.createdAt).setHours(0, 0, 0, 0)
    if (age <= 0) buckets[0].sessions.push(s)
    else if (age <= dayMs) buckets[1].sessions.push(s)
    else if (age <= dayMs * 7) buckets[2].sessions.push(s)
    else buckets[3].sessions.push(s)
  }

  return buckets.filter((b) => b.sessions.length > 0)
}

export function deriveTitle(firstUserText: string): string {
  const trimmed = firstUserText.trim()
  if (trimmed.length <= 48) return trimmed
  return trimmed.slice(0, 45).trimEnd() + '...'
}
