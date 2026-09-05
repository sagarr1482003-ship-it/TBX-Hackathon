import type { ChatSession } from './types'

const KEY = 'verity-sessions-v1'

export function loadSessions(): ChatSession[] | null {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed) || !parsed.length) return null
    return parsed as ChatSession[]
  } catch {
    return null
  }
}

export function saveSessions(sessions: ChatSession[]) {
  try {
    localStorage.setItem(KEY, JSON.stringify(sessions))
  } catch {
    // storage full or unavailable - non-critical, fail silently
  }
}
