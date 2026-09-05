/**
 * Hand-rolled Server-Sent Events reader for POST endpoints.
 *
 * The native EventSource API is GET-only, and the backend's chat route is
 * `POST /api/chat/stream` (the question travels in the JSON body). So we issue
 * a normal fetch and parse the `event:` / `data:` frames off the response body
 * stream ourselves. No extra dependencies.
 */

import type { AgentStreamEvent } from './types'

export interface StreamHandlers {
  onEvent?: (evt: AgentStreamEvent) => void
  onError?: (err: unknown) => void
}

/** Parse one raw SSE frame (a block of lines) into an event, or null if unusable. */
function parseFrame(raw: string): AgentStreamEvent | null {
  let event = 'message'
  const dataLines: string[] = []

  for (const line of raw.split('\n')) {
    // Comment / keepalive ping frames from sse-starlette
    if (line.startsWith(':')) continue

    const colon = line.indexOf(':')
    const field = colon === -1 ? line : line.slice(0, colon)
    let value = colon === -1 ? '' : line.slice(colon + 1)
    // Spec: strip exactly one leading space after the colon
    if (value.startsWith(' ')) value = value.slice(1)

    if (field === 'event') event = value
    else if (field === 'data') dataLines.push(value)
    // id / retry / unknown fields are ignored
  }

  if (!dataLines.length) return null

  try {
    const data = JSON.parse(dataLines.join('\n')) as Record<string, unknown>
    return { event, data }
  } catch {
    // Malformed payload: skip the frame rather than killing the stream
    return null
  }
}

/**
 * POST an SSE request and stream back decoded frames.
 * Returns an abort function.
 */
export function streamChat(
  url: string,
  question: string,
  handlers: StreamHandlers,
  headers?: Record<string, string>,
): () => void {
  const controller = new AbortController()

  void (async () => {
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
          ...headers,
        },
        body: JSON.stringify({ q: question }),
        signal: controller.signal,
      })

      if (!res.ok || !res.body) {
        const body = res.ok ? '' : await res.text().catch(() => '')
        handlers.onError?.(
          new Error(`Chat stream failed: HTTP ${res.status}${body ? ` — ${body.slice(0, 200)}` : ''}`),
        )
        return
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      const drain = (flush: boolean) => {
        // Normalise CRLF so a single blank-line split handles both separators
        buffer = buffer.replace(/\r\n/g, '\n')
        const frames = buffer.split('\n\n')
        // The trailing chunk may be a partial frame — keep it buffered unless flushing
        buffer = flush ? '' : (frames.pop() ?? '')
        for (const raw of frames) {
          if (!raw.trim()) continue
          const evt = parseFrame(raw)
          if (evt) handlers.onEvent?.(evt)
        }
      }

      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        drain(false)
      }

      buffer += decoder.decode()
      drain(true)
    } catch (err) {
      // An explicit abort is a normal caller-initiated teardown, not an error
      if (err instanceof DOMException && err.name === 'AbortError') return
      if (err instanceof Error && err.name === 'AbortError') return
      handlers.onError?.(err)
    }
  })()

  return () => controller.abort()
}
