import { useEffect, useRef, useState, useCallback } from 'react'
import { ChatsCircle, Receipt, SidebarSimple } from '@phosphor-icons/react'
import { Header } from './components/Header'
import { Composer } from './components/Composer'
import { UserBubble, AssistantBubble } from './components/MessageBubble'
import { ThinkingBubble } from './components/ThinkingBubble'
import { EvidencePanel } from './components/EvidencePanel'
import { Sidebar } from './components/Sidebar'
import { Buddy } from './components/Buddy'
import { VoiceAgent } from './components/VoiceAgent'
import { submitTurnStreaming } from './lib/api'
import { agentCompletionToQueryResult } from './lib/adapter'
import type { ChatSession, QueryResult, Turn } from './lib/types'
import { deriveTitle } from './lib/sessionGroups'
import { loadSessions, saveSessions } from './lib/storage'

/** Short, human-readable label per pipeline stage, shown while the turn streams. */
const STAGE_LABELS: Record<string, string> = {
  intake: 'Reading the question',
  sql_generation: 'Writing SQL',
  static_validation: 'Checking the SQL is safe',
  reviewer_verdict: 'Reviewing the query',
  execution: 'Running the query',
  answer_composition: 'Writing the answer',
  clarification: 'Asking a follow-up',
}

function makeSeededSession(): ChatSession {
  return {
    id: `s-seed-${Date.now()}`,
    title: 'New chat',
    createdAt: Date.now(),
    turns: [],
    context: {},
    activeResultId: undefined,
  }
}

function makeEmptySession(): ChatSession {
  return {
    id: `s-${Date.now()}-${Math.floor(Math.random() * 1000)}`,
    title: 'New chat',
    createdAt: Date.now(),
    turns: [],
    context: {},
    activeResultId: undefined,
  }
}

export default function App() {
  const [initial] = useState(() => {
    const loaded = loadSessions()
    if (loaded && loaded.length) return { sessions: loaded, activeId: loaded[0].id }
    const seeded = makeSeededSession()
    return { sessions: [seeded], activeId: seeded.id }
  })

  const [sessions, setSessions] = useState<ChatSession[]>(initial.sessions)
  const [activeSessionId, setActiveSessionId] = useState<string>(initial.activeId)
  const [isThinking, setIsThinking] = useState(false)
  const [stageLabel, setStageLabel] = useState<string | null>(null)
  const [mobileView, setMobileView] = useState<'chat' | 'evidence'>('chat')
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [voiceAgentOpen, setVoiceAgentOpen] = useState(false)
  const [leftPaneOpen, setLeftPaneOpen] = useState(true)
  const [rightPaneOpen, setRightPaneOpen] = useState(true)
  
  // Resizable pane widths
  const [leftWidth, setLeftWidth] = useState(256)
  const [rightWidth, setRightWidth] = useState(380)
  
  const isDraggingLeft = useRef(false)
  const isDraggingRight = useRef(false)
  
  const handleMouseMove = useCallback((e: MouseEvent) => {
    if (isDraggingLeft.current) {
      setLeftWidth(Math.min(Math.max(160, e.clientX), 480))
    }
    if (isDraggingRight.current) {
      setRightWidth(Math.min(Math.max(250, window.innerWidth - e.clientX), 600))
    }
  }, [])
  
  const handleMouseUp = useCallback(() => {
    isDraggingLeft.current = false
    isDraggingRight.current = false
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }, [])
  
  useEffect(() => {
    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }
  }, [handleMouseMove, handleMouseUp])

  const [dark, setDark] = useState(() => {
    if (typeof window === 'undefined') return false
    const stored = localStorage.getItem('verity-theme')
    if (stored) return stored === 'dark'
    return window.matchMedia('(prefers-color-scheme: dark)').matches
  })

  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark)
    localStorage.setItem('verity-theme', dark ? 'dark' : 'light')
  }, [dark])

  useEffect(() => {
    saveSessions(sessions)
  }, [sessions])

  const activeSession = sessions.find((s) => s.id === activeSessionId) ?? sessions[0]

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [activeSession?.turns.length, isThinking])

  function submitToSession(sessionId: string, text: string) {
    const userTurn: Turn = { id: `u-${Date.now()}`, role: 'user', text }
    setSessions((prev) =>
      prev.map((s) =>
        s.id === sessionId
          ? { ...s, turns: [...s.turns, userTurn], title: s.turns.length === 0 ? deriveTitle(text) : s.title }
          : s,
      ),
    )
    setIsThinking(true)
    setStageLabel(STAGE_LABELS.intake)

    const appendResult = (result: QueryResult) => {
      setSessions((prev) =>
        prev.map((s) => {
          if (s.id !== sessionId) return s
          return {
            ...s,
            turns: [...s.turns, { id: `a-${Date.now()}`, role: 'assistant', result }],
            context: {},
            activeResultId: result.id,
          }
        }),
      )
    }

    // Stream the real pipeline: each SSE stage updates the thinking indicator,
    // the terminal `completion` frame carries the answer.
    submitTurnStreaming(
      text,
      (evt) => {
        if (evt.event in STAGE_LABELS) setStageLabel(STAGE_LABELS[evt.event])
      },
      (completion, events) => {
        appendResult(agentCompletionToQueryResult(completion, events))
        setIsThinking(false)
        setStageLabel(null)
        setMobileView('evidence')
      },
      (err) => {
        console.error('Turn submission failed:', err)
        appendResult(
          agentCompletionToQueryResult({
            question: text,
            outcome: 'review_failed',
            clarification: null,
            resolved_sql: null,
            answer_text: null,
            answer_source: null,
            chart: null,
            verdict: null,
            breakdown: null,
            validation_ok: false,
            validation_reason: 'The request to the assistant failed. Please try again.',
            total_ms: 0,
          }),
        )
        setIsThinking(false)
        setStageLabel(null)
      },
    )
  }

  function handleSubmit(text: string) {
    submitToSession(activeSessionId, text)
  }

  function handleNewSession() {
    const s = makeEmptySession()
    setSessions((prev) => [s, ...prev])
    setActiveSessionId(s.id)
    setSidebarOpen(false)
    setMobileView('chat')
  }

  function handleSelectSession(id: string) {
    setActiveSessionId(id)
    setSidebarOpen(false)
    setMobileView('chat')
  }

  function handleRenameSession(id: string, title: string) {
    setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, title } : s)))
  }

  function handleDeleteSession(id: string) {
    setSessions((prev) => {
      const filtered = prev.filter((s) => s.id !== id)
      const finalList = filtered.length ? filtered : [makeEmptySession()]
      if (id === activeSessionId) setActiveSessionId(finalList[0].id)
      return finalList
    })
  }

  const activeResult = activeSession?.turns.find(
    (t) => t.role === 'assistant' && t.result.id === activeSession.activeResultId,
  ) as Extract<Turn, { role: 'assistant' }> | undefined

  return (
    <div className="flex h-[100dvh] flex-col bg-paper dark:bg-paper-dark">
      <Header dark={dark} onToggleTheme={() => setDark((d) => !d)} onMenuClick={() => setSidebarOpen((o) => !o)} />

      <div className="relative flex min-h-0 flex-1">
        {leftPaneOpen ? (
          <>
            <aside 
              className="hidden shrink-0 border-r border-line dark:border-line-dark md:flex relative"
              style={{ width: leftWidth }}
            >
              <Sidebar
                sessions={sessions}
                activeSessionId={activeSessionId}
                onSelect={handleSelectSession}
                onNew={handleNewSession}
                onRename={handleRenameSession}
                onDelete={handleDeleteSession}
                onCollapse={() => setLeftPaneOpen(false)}
              />
              <div 
                className="absolute -right-[3px] top-0 bottom-0 w-[6px] cursor-col-resize z-10 hover:bg-accent/20 dark:hover:bg-accent-dark/20 transition-colors"
                onMouseDown={(e) => {
                  e.preventDefault()
                  isDraggingLeft.current = true
                  document.body.style.cursor = 'col-resize'
                  document.body.style.userSelect = 'none'
                }}
              />
            </aside>
          </>
        ) : (
          <div className="hidden shrink-0 flex-col items-center border-r border-line pt-3 dark:border-line-dark md:flex md:w-12">
            <button
              onClick={() => setLeftPaneOpen(true)}
              aria-label="Show chat history"
              title="Show chat history"
              className="flex h-9 w-9 items-center justify-center rounded-[10px] text-ink-faint hover:bg-sunken hover:text-ink dark:text-ink-faint-dark dark:hover:bg-sunken-dark dark:hover:text-ink-dark"
            >
              <SidebarSimple size={17} />
            </button>
          </div>
        )}

        <div className={`fixed inset-0 z-50 md:hidden ${sidebarOpen ? '' : 'pointer-events-none'}`}>
          <div
            onClick={() => setSidebarOpen(false)}
            className={`absolute inset-0 bg-ink/40 transition-opacity dark:bg-black/60 ${sidebarOpen ? 'opacity-100' : 'opacity-0'}`}
          />
          <div
            className={`absolute inset-y-0 left-0 w-72 max-w-[85vw] transform border-r border-line bg-paper transition-transform duration-200 ease-out dark:border-line-dark dark:bg-paper-dark ${
              sidebarOpen ? 'translate-x-0' : '-translate-x-full'
            }`}
          >
            <Sidebar
              sessions={sessions}
              activeSessionId={activeSessionId}
              onSelect={handleSelectSession}
              onNew={handleNewSession}
              onRename={handleRenameSession}
              onDelete={handleDeleteSession}
            />
          </div>
        </div>

        <div
          className={`flex min-h-0 min-w-0 flex-1 ${
            rightPaneOpen ? 'lg:grid' : 'lg:flex'
          }`}
          style={{
            gridTemplateColumns: rightPaneOpen ? `minmax(0,1fr) ${rightWidth}px` : undefined
          }}
        >
          <section
            className={`${mobileView === 'chat' ? 'flex' : 'hidden'} min-h-0 min-w-0 flex-1 flex-col lg:flex lg:border-r lg:border-line lg:dark:border-line-dark`}
          >
            <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-5 pb-24 sm:px-6">
              {activeSession?.turns.map((turn) =>
                turn.role === 'user' ? (
                  <UserBubble key={turn.id} text={turn.text} />
                ) : (
                  <AssistantBubble
                    key={turn.id}
                    result={turn.result}
                    active={turn.result.id === activeSession.activeResultId}
                    onSelect={() => {
                      setSessions((prev) => prev.map((s) => (s.id === activeSessionId ? { ...s, activeResultId: turn.result.id } : s)))
                      setMobileView('evidence')
                    }}
                  />
                ),
              )}
              {isThinking && <ThinkingBubble label={stageLabel ?? undefined} />}
            </div>
            <Composer onSubmit={handleSubmit} disabled={isThinking} />
          </section>

          <section
            className={`relative ${mobileView === 'evidence' ? 'flex' : 'hidden'} min-h-0 min-w-0 flex-1 flex-col ${
              rightPaneOpen ? 'lg:flex' : 'lg:hidden'
            }`}
          >
            <div 
              className="absolute -left-[3px] top-0 bottom-0 w-[6px] cursor-col-resize z-10 hover:bg-accent/20 dark:hover:bg-accent-dark/20 transition-colors hidden lg:block"
              onMouseDown={(e) => {
                e.preventDefault()
                isDraggingRight.current = true
                document.body.style.cursor = 'col-resize'
                document.body.style.userSelect = 'none'
              }}
            />
            <EvidencePanel result={activeResult?.result} onCollapse={() => setRightPaneOpen(false)} />
          </section>
        </div>

        {!rightPaneOpen && (
          <div className="hidden shrink-0 flex-col items-center border-l border-line pt-3 dark:border-line-dark lg:flex lg:w-12">
            <button
              onClick={() => setRightPaneOpen(true)}
              aria-label="Show evidence panel"
              title="Show evidence panel"
              className="flex h-9 w-9 items-center justify-center rounded-[10px] text-ink-faint hover:bg-sunken hover:text-ink dark:text-ink-faint-dark dark:hover:bg-sunken-dark dark:hover:text-ink-dark"
            >
              <Receipt size={17} />
            </button>
          </div>
        )}
      </div>

      <nav className="grid grid-cols-2 border-t border-line dark:border-line-dark lg:hidden">
        <button
          onClick={() => setMobileView('chat')}
          className={`flex items-center justify-center gap-1.5 py-2.5 text-xs font-medium ${
            mobileView === 'chat' ? 'text-accent dark:text-accent-dark' : 'text-ink-faint dark:text-ink-faint-dark'
          }`}
        >
          <ChatsCircle size={15} />
          Chat
        </button>
        <button
          onClick={() => setMobileView('evidence')}
          className={`flex items-center justify-center gap-1.5 py-2.5 text-xs font-medium ${
            mobileView === 'evidence' ? 'text-accent dark:text-accent-dark' : 'text-ink-faint dark:text-ink-faint-dark'
          }`}
        >
          <Receipt size={15} />
          Evidence
        </button>
      </nav>

      <div className="fixed bottom-36 right-4 z-40 lg:bottom-20 lg:right-6">
        <button
          onClick={() => setVoiceAgentOpen(true)}
          aria-label="Start Live Voice"
          className="flex h-12 w-12 items-center justify-center rounded-full bg-accent text-paper shadow-[0_8px_24px_rgba(15,107,82,0.3)] transition-transform hover:scale-105 active:scale-95 dark:bg-accent-dark dark:text-paper-dark dark:shadow-[0_8px_24px_rgba(52,199,158,0.4)]"
        >
          <svg width="20" height="20" viewBox="0 0 256 256" fill="currentColor">
            <path d="M128,176a48.05,48.05,0,0,0,48-48V64a48,48,0,0,0-96,0v64A48.05,48.05,0,0,0,128,176ZM96,64a32,32,0,0,1,64,0v64a32,32,0,0,1-64,0ZM200,128a8,8,0,0,1-16,0,56,56,0,0,1-112,0,8,8,0,0,1-16,0,72.08,72.08,0,0,0,64,71.49V232a8,8,0,0,0,16,0V199.49A72.08,72.08,0,0,0,200,128Z"></path>
          </svg>
        </button>
      </div>

      <Buddy onAsk={handleSubmit} />

      {voiceAgentOpen && (
        <VoiceAgent onClose={() => setVoiceAgentOpen(false)} onAsk={handleSubmit} />
      )}
    </div>
  )
}
