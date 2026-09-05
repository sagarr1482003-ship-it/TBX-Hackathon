/**
 * API service layer — talks to the backend's HTTP API.
 *
 * When USE_MOCK is true (default until the backend is live), all calls are
 * routed to mockApi.ts which returns static fixtures matching the exact BE
 * response shapes from docs/api.md.
 *
 * Monetary values are kept as strings end-to-end — never parsed to number.
 */

import type {
  SessionCreated,
  TurnResponse,
  TraceEvent,
  Page,
  SessionSummary,
  HealthPayload,
  AgentCompletion,
  AgentStreamEvent,
} from './types'
import * as mock from './mockApi'
import { streamChat } from './sse'

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
const AUTH_TOKEN: string | undefined = import.meta.env.VITE_API_TOKEN
const USE_MOCK = (import.meta.env.VITE_USE_MOCK ?? 'true') === 'true'

// The real streaming chat endpoint. Leave VITE_API_BASE_URL empty in dev so this
// goes through the Vite proxy (avoids CORS); set it to reach a remote backend.
const SSE_BASE = import.meta.env.VITE_API_BASE_URL ?? ''
const CHAT_STREAM_PATH = `${SSE_BASE}/api/chat/stream`

function headers(extra?: Record<string, string>): Record<string, string> {
  const h: Record<string, string> = { 'Content-Type': 'application/json', ...extra }
  if (AUTH_TOKEN) h['X-Internal-Token'] = AUTH_TOKEN
  return h
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: headers(init?.headers as Record<string, string> | undefined),
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new ApiError(res.status, body, path)
  }
  return res.json() as Promise<T>
}

export class ApiError extends Error {
  status: number
  body: string
  path: string

  constructor(status: number, body: string, path: string) {
    super(`API ${status} at ${path}: ${body.slice(0, 200)}`)
    this.name = 'ApiError'
    this.status = status
    this.body = body
    this.path = path
  }
}

// ---------------------------------------------------------------------------
// Session management
// ---------------------------------------------------------------------------

export async function createSession(surface: 'finance' | 'insights' = 'finance'): Promise<SessionCreated> {
  if (USE_MOCK) return mock.createSession(surface)
  // Real backend: POST /api/chat/session returns { session_id }. Shape it into SessionCreated
  // so the rest of the FE (which expects the richer contract) keeps working.
  const created = await apiFetch<{ session_id: string }>('/api/chat/session', {
    method: 'POST',
    body: JSON.stringify({ surface }),
  })
  return {
    session_id: created.session_id,
    surface,
    starter_questions: [],
    dataset_version: 1,
  } as SessionCreated
}

export async function listSessions(cursor?: string, pageSize = 20): Promise<Page<SessionSummary>> {
  if (USE_MOCK) return mock.listSessions()
  const params = new URLSearchParams({ page_size: String(pageSize) })
  if (cursor) params.set('cursor', cursor)
  return apiFetch<Page<SessionSummary>>(`/api/sessions?${params}`)
}

export async function deleteSession(sessionId: string): Promise<void> {
  if (USE_MOCK) return
  await apiFetch(`/api/sessions/${sessionId}`, { method: 'DELETE' })
}

// ---------------------------------------------------------------------------
// Chat turns
// ---------------------------------------------------------------------------

export async function submitTurn(
  sessionId: string,
  question: string,
  options?: { detailed?: boolean; language_code?: string },
): Promise<TurnResponse> {
  if (USE_MOCK) return mock.submitTurn(sessionId, question)
  return apiFetch<TurnResponse>(`/api/sessions/${sessionId}/turns`, {
    method: 'POST',
    body: JSON.stringify({ question, ...options }),
  })
}

/**
 * Submit a question to the real streaming pipeline (POST /api/chat/stream).
 *
 * Every SSE frame is forwarded to `onStage` as it arrives, so the UI can show
 * live progress. The terminal `completion` frame carries the full answer and is
 * delivered to `onComplete` along with every event observed on the way there.
 *
 * Returns an abort function.
 */
export function submitTurnStreaming(
  question: string,
  onStage: (evt: AgentStreamEvent) => void,
  onComplete: (completion: AgentCompletion, events: AgentStreamEvent[]) => void,
  onError?: (err: unknown) => void,
  sessionId?: string,
): () => void {
  const events: AgentStreamEvent[] = []

  return streamChat(
    CHAT_STREAM_PATH,
    question,
    {
      onEvent: (evt) => {
        // Stamp receipt time so the adapter can measure per-stage durations —
        // the stream itself carries no per-stage timing.
        const stamped: AgentStreamEvent = { ...evt, receivedAt: Date.now() }
        events.push(stamped)
        onStage(stamped)
        if (stamped.event === 'completion') {
          onComplete(stamped.data as unknown as AgentCompletion, events)
        }
      },
      onError,
    },
    AUTH_TOKEN ? { 'X-Internal-Token': AUTH_TOKEN } : undefined,
    sessionId,
  )
}

export async function getTurn(turnId: string): Promise<TurnResponse> {
  if (USE_MOCK) return mock.getAnsweredTurn()
  return apiFetch<TurnResponse>(`/api/turns/${turnId}`)
}

export async function submitClarification(sessionId: string, answer: string): Promise<TurnResponse> {
  if (USE_MOCK) return mock.submitTurn(sessionId, answer)
  return apiFetch<TurnResponse>(`/api/sessions/${sessionId}/clarifications`, {
    method: 'POST',
    body: JSON.stringify({ answer }),
  })
}

export async function submitFeedback(
  turnId: string,
  rating: 'positive' | 'negative',
  text?: string,
): Promise<void> {
  if (USE_MOCK) return
  await apiFetch(`/api/turns/${turnId}/feedback`, {
    method: 'POST',
    body: JSON.stringify({ rating, text }),
  })
}

// ---------------------------------------------------------------------------
// Buddy suggestions
// ---------------------------------------------------------------------------

export async function getStarterQuestions(sessionId?: string): Promise<string[]> {
  if (USE_MOCK) return mock.getStarterQuestions()
  const params = sessionId ? `?session_id=${sessionId}` : ''
  const res = await apiFetch<{ questions: string[] }>(`/api/buddy/starters${params}`)
  return res.questions
}

export async function getNextQuestions(turnId: string): Promise<string[]> {
  if (USE_MOCK) return mock.getNextQuestions()
  const res = await apiFetch<{ questions: string[] }>(`/api/buddy/next-questions?turn_id=${turnId}`)
  return res.questions
}

// ---------------------------------------------------------------------------
// Export
// ---------------------------------------------------------------------------

export async function exportTurn(turnId: string, format: 'csv' | 'xlsx' = 'csv'): Promise<Blob> {
  if (USE_MOCK) return new Blob(['mock export data'], { type: 'text/csv' })
  const res = await fetch(`${BASE_URL}/api/turns/${turnId}/export?format=${format}`, {
    headers: headers(),
  })
  if (!res.ok) throw new ApiError(res.status, await res.text(), `/api/turns/${turnId}/export`)
  return res.blob()
}

// ---------------------------------------------------------------------------
// Trace stream (SSE)
// ---------------------------------------------------------------------------

export function openTraceStream(
  turnId: string,
  onEvent: (event: TraceEvent) => void,
  onDone?: () => void,
): { close: () => void } {
  if (USE_MOCK) return mock.openTraceStream(onEvent, onDone)

  const es = new EventSource(`${BASE_URL}/api/turns/${turnId}/trace/stream`)

  es.addEventListener('trace', (e) => {
    const ev: TraceEvent = JSON.parse((e as MessageEvent).data)
    onEvent(ev)
    if (ev.stage === 'completion') {
      es.close()
      onDone?.()
    }
  })

  // Keepalives carry no sequence — ignore them
  es.addEventListener('keepalive', () => {})

  es.onerror = () => {
    es.close()
    onDone?.()
  }

  return { close: () => es.close() }
}

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

export async function checkHealth(): Promise<HealthPayload> {
  if (USE_MOCK) return mock.checkHealth()
  return apiFetch<HealthPayload>('/health')
}
