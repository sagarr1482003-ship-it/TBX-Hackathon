import { useEffect, useRef, useState } from 'react'
import { ArrowRight, ArrowsCounterClockwise, Microphone, Stop, Translate, Waveform, X } from '@phosphor-icons/react'

type BuddyState = 'idle' | 'listening' | 'framing'

const LANGUAGES = ['English', 'Hindi', 'Tamil', 'Telugu', 'Bengali', 'Marathi', 'Kannada']

const SCENARIOS = [
  {
    raw: "umm like, how much did we... receive in credits, last month or something?",
    framed: 'What was the total volume of credit transactions last month?',
  },
  {
    raw: "is there an account with like, a really huge balance?",
    framed: 'Which account has the highest available balance?',
  },
  {
    raw: 'did anyone withdraw a weirdly large amount recently? like more than usual',
    framed: 'Any unusual debit transactions recently?',
  },
]

export function Buddy({ onAsk }: { onAsk: (question: string) => void }) {
  const [open, setOpen] = useState(false)
  const [state, setState] = useState<BuddyState>('idle')
  const [language, setLanguage] = useState('English')
  const [scenarioIndex, setScenarioIndex] = useState(0)
  const [revealedChars, setRevealedChars] = useState(0)
  const timerRef = useRef<number | null>(null)

  const scenario = SCENARIOS[scenarioIndex]

  useEffect(() => {
    return () => {
      if (timerRef.current) window.clearInterval(timerRef.current)
    }
  }, [])

  function startListening() {
    setState('listening')
    setRevealedChars(0)
    const text = scenario.raw
    let i = 0
    timerRef.current = window.setInterval(() => {
      i += 1
      setRevealedChars(i)
      if (i >= text.length) {
        if (timerRef.current) window.clearInterval(timerRef.current)
        window.setTimeout(() => setState('framing'), 500)
      }
    }, 28)
  }

  function stopListening() {
    if (timerRef.current) window.clearInterval(timerRef.current)
    setRevealedChars(scenario.raw.length)
    setState('framing')
  }

  function reset() {
    if (timerRef.current) window.clearInterval(timerRef.current)
    setState('idle')
    setRevealedChars(0)
    setScenarioIndex((i) => (i + 1) % SCENARIOS.length)
  }

  function askVerity() {
    onAsk(scenario.framed)
    setOpen(false)
    reset()
  }

  return (
    <div className="fixed bottom-20 right-4 z-40 lg:bottom-6 lg:right-6">
      {open && (
        <div className="mb-3 w-[min(360px,calc(100vw-2rem))] overflow-hidden rounded-[10px] border border-line bg-surface shadow-[0_12px_40px_rgba(0,0,0,0.12)] dark:border-line-dark dark:bg-surface-dark dark:shadow-[0_12px_40px_rgba(0,0,0,0.5)]">
          <div className="flex items-center gap-2.5 border-b border-line px-4 py-3 dark:border-line-dark">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent dark:bg-accent-soft-dark dark:text-accent-dark">
              <Waveform size={15} weight="bold" />
            </span>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium text-ink dark:text-ink-dark">Buddy</div>
              <div className="truncate text-xs text-ink-faint dark:text-ink-faint-dark">Helps you frame the question</div>
            </div>
            <button
              onClick={() => setOpen(false)}
              aria-label="Close Buddy"
              className="shrink-0 rounded-[8px] p-1.5 text-ink-faint hover:bg-sunken hover:text-ink dark:text-ink-faint-dark dark:hover:bg-sunken-dark dark:hover:text-ink-dark"
            >
              <X size={15} />
            </button>
          </div>

          <div className="border-b border-line px-4 py-3 dark:border-line-dark">
            <div className="flex flex-wrap gap-1.5">
              {LANGUAGES.map((lang) => (
                <button
                  key={lang}
                  onClick={() => setLanguage(lang)}
                  className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${
                    language === lang
                      ? 'border-accent/40 bg-accent-soft text-accent-strong dark:border-accent-dark/40 dark:bg-accent-soft-dark dark:text-accent-dark'
                      : 'border-line text-ink-muted hover:border-ink-faint/40 dark:border-line-dark dark:text-ink-muted-dark'
                  }`}
                >
                  {lang}
                </button>
              ))}
            </div>
            <p className="mt-2 flex items-center gap-1.5 text-[11px] text-ink-faint dark:text-ink-faint-dark">
              <Translate size={12} />
              Multilingual voice via Sarvam AI, coming soon. This demo shows the flow in English.
            </p>
          </div>

          <div className="flex min-h-[220px] flex-col justify-between p-4">
            {state === 'idle' && (
              <div className="flex flex-1 flex-col items-center justify-center gap-4 text-center">
                <p className="max-w-[26ch] text-sm leading-relaxed text-ink-muted dark:text-ink-muted-dark">
                  Not sure how to ask? Tap the mic and talk it through in your own words. Buddy will turn it into a clean
                  question for Verity.
                </p>
                <button
                  onClick={startListening}
                  aria-label="Start talking to Buddy"
                  className="flex h-14 w-14 items-center justify-center rounded-full bg-ink text-paper transition-transform active:scale-95 dark:bg-ink-dark dark:text-paper-dark"
                >
                  <Microphone size={22} weight="fill" />
                </button>
              </div>
            )}

            {state === 'listening' && (
              <div className="flex flex-1 flex-col items-center justify-center gap-4">
                <div className="flex h-10 items-end gap-1">
                  {[0, 1, 2, 3, 4].map((i) => (
                    <span
                      key={i}
                      className="buddy-bar w-1 rounded-full bg-accent dark:bg-accent-dark"
                      style={{ height: '100%', animationDelay: `${i * 0.12}s` }}
                    />
                  ))}
                </div>
                <p className="min-h-[3.5rem] max-w-[28ch] text-center text-sm leading-relaxed text-ink dark:text-ink-dark">
                  {scenario.raw.slice(0, revealedChars)}
                  <span className="animate-pulse">|</span>
                </p>
                <button
                  onClick={stopListening}
                  className="flex items-center gap-1.5 rounded-full border border-line px-3 py-1.5 text-xs font-medium text-ink-muted hover:bg-sunken dark:border-line-dark dark:text-ink-muted-dark dark:hover:bg-sunken-dark"
                >
                  <Stop size={13} weight="fill" />
                  Stop
                </button>
              </div>
            )}

            {state === 'framing' && (
              <div className="flex flex-1 flex-col justify-center gap-3">
                <div>
                  <p className="mb-1 text-xs font-medium text-ink-faint dark:text-ink-faint-dark">Buddy heard</p>
                  <p className="text-sm italic leading-relaxed text-ink-muted dark:text-ink-muted-dark">"{scenario.raw}"</p>
                </div>
                <div className="rounded-[10px] border border-accent/25 bg-accent-soft px-3.5 py-3 dark:border-accent-dark/25 dark:bg-accent-soft-dark">
                  <p className="mb-1 text-xs font-medium text-accent-strong dark:text-accent-dark">A clean question for Verity</p>
                  <p className="text-sm leading-relaxed text-ink dark:text-ink-dark">{scenario.framed}</p>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={reset}
                    className="flex items-center gap-1.5 rounded-[10px] border border-line px-3 py-2 text-xs font-medium text-ink-muted hover:bg-sunken dark:border-line-dark dark:text-ink-muted-dark dark:hover:bg-sunken-dark"
                  >
                    <ArrowsCounterClockwise size={13} />
                    Try again
                  </button>
                  <button
                    onClick={askVerity}
                    className="flex flex-1 items-center justify-center gap-1.5 rounded-[10px] bg-ink px-3 py-2 text-xs font-medium text-paper hover:opacity-90 dark:bg-ink-dark dark:text-paper-dark"
                  >
                    Ask Verity
                    <ArrowRight size={13} />
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      <button
        onClick={() => setOpen((o) => !o)}
        aria-label={open ? 'Close Buddy' : 'Open Buddy'}
        className="flex items-center gap-2 rounded-full bg-ink px-4 py-3 text-sm font-medium text-paper shadow-[0_8px_24px_rgba(0,0,0,0.18)] transition-transform hover:scale-[1.03] active:scale-95 dark:bg-ink-dark dark:text-paper-dark dark:shadow-[0_8px_24px_rgba(0,0,0,0.5)]"
      >
        <Waveform size={16} weight="bold" className="text-accent-dark" />
        Buddy
      </button>
    </div>
  )
}
