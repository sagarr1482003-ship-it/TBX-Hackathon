import { useState } from 'react'
import { ArrowUp, Microphone, Stop, X, CircleNotch } from '@phosphor-icons/react'
import { useAudioRecorder } from '../lib/useAudioRecorder'
import { transcribeAudio } from '../lib/api'

const SUGGESTIONS = [
  'Which transactions are still unreconciled?',
  'How much did we spend on logistics this month?',
  'Any unusual vendor payments recently?',
  "What's our projected profit for next quarter?",
]

function formatDuration(total: number): string {
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${s.toString().padStart(2, '0')}`
}

export function Composer({ onSubmit, disabled }: { onSubmit: (text: string) => void; disabled: boolean }) {
  const [value, setValue] = useState('')
  const [transcribing, setTranscribing] = useState(false)
  const [voiceError, setVoiceError] = useState<string | null>(null)
  const recorder = useAudioRecorder()

  const isRecording = recorder.status === 'recording' || recorder.status === 'stopping'

  function submit() {
    const trimmed = value.trim()
    if (!trimmed || disabled) return
    onSubmit(trimmed)
    setValue('')
  }

  async function startRecording() {
    setVoiceError(null)
    await recorder.start()
  }

  async function stopAndTranscribe() {
    const blob = await recorder.stop()
    if (!blob) return
    setTranscribing(true)
    setVoiceError(null)
    try {
      const { text } = await transcribeAudio(blob)
      const clean = text.trim()
      if (clean) {
        // ChatGPT behaviour: drop the transcript into the composer so the user
        // can review/edit, then send it straight to the chat endpoint.
        onSubmit(clean)
        setValue('')
      } else {
        setVoiceError("Didn't catch that — try again.")
      }
    } catch (err) {
      console.error('Transcription failed:', err)
      setVoiceError('Transcription failed. Please try again.')
    } finally {
      setTranscribing(false)
    }
  }

  function cancelRecording() {
    recorder.cancel()
    setVoiceError(null)
  }

  const error = voiceError ?? recorder.error

  return (
    <div className="shrink-0 border-t border-line px-4 py-3.5 dark:border-line-dark sm:px-5">
      <div className="mb-2.5 flex flex-wrap gap-1.5">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            onClick={() => onSubmit(s)}
            disabled={disabled || isRecording || transcribing}
            className="rounded-full border border-line px-3 py-1.5 text-xs text-ink-muted transition-colors hover:border-ink-faint/50 hover:text-ink disabled:opacity-50 dark:border-line-dark dark:text-ink-muted-dark dark:hover:text-ink-dark"
          >
            {s}
          </button>
        ))}
      </div>

      {error && (
        <p className="mb-2 text-xs text-brick dark:text-brick-dark" role="alert">
          {error}
        </p>
      )}

      {isRecording ? (
        /* Recording bar — cancel, live waveform + timer, stop-and-send */
        <div className="flex items-center gap-3 rounded-[10px] border border-accent/50 bg-surface px-3 py-2 dark:border-accent-dark/50 dark:bg-surface-dark">
          <button
            onClick={cancelRecording}
            aria-label="Cancel recording"
            title="Cancel"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-ink-muted transition-colors hover:bg-sunken hover:text-ink dark:text-ink-muted-dark dark:hover:bg-sunken-dark dark:hover:text-ink-dark"
          >
            <X size={16} weight="bold" />
          </button>

          <div className="flex flex-1 items-center gap-2.5">
            <span className="relative flex h-2.5 w-2.5 shrink-0">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brick opacity-75 dark:bg-brick-dark" />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-brick dark:bg-brick-dark" />
            </span>
            <div className="flex flex-1 items-center gap-1 overflow-hidden">
              {Array.from({ length: 28 }).map((_, i) => {
                // Center bars react more strongly to the live amplitude.
                const distance = Math.abs(i - 14) / 14
                const height = 3 + recorder.amplitude * 22 * (1 - distance * 0.6)
                return (
                  <span
                    key={i}
                    className="w-1 shrink-0 rounded-full bg-accent/70 transition-[height] duration-100 dark:bg-accent-dark/70"
                    style={{ height: `${Math.max(3, height)}px` }}
                  />
                )
              })}
            </div>
            <span className="shrink-0 font-mono text-xs tabular-nums text-ink-muted dark:text-ink-muted-dark">
              {formatDuration(recorder.seconds)}
            </span>
          </div>

          <button
            onClick={stopAndTranscribe}
            aria-label="Stop and send"
            title="Stop & send"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent text-paper transition-transform hover:scale-105 active:scale-95 dark:bg-accent-dark dark:text-paper-dark"
          >
            <Stop size={15} weight="fill" />
          </button>
        </div>
      ) : (
        /* Normal composer — text + mic + send */
        <div className="flex items-end gap-2 rounded-[10px] border border-line bg-surface px-3 py-2 focus-within:border-accent/50 dark:border-line-dark dark:bg-surface-dark dark:focus-within:border-accent-dark/50">
          <textarea
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                submit()
              }
            }}
            rows={1}
            disabled={transcribing}
            placeholder={transcribing ? 'Transcribing…' : 'Ask about spend, payouts, or reconciliation status...'}
            className="max-h-28 flex-1 resize-none bg-transparent py-1 text-sm text-ink placeholder:text-ink-faint focus:outline-none disabled:opacity-60 dark:text-ink-dark dark:placeholder:text-ink-faint-dark"
          />

          {/* Mic is always available; the send button appears when there's text. */}
          <button
            onClick={startRecording}
            disabled={disabled || transcribing || !recorder.isSupported}
            aria-label={recorder.isSupported ? 'Record voice message' : 'Recording not supported'}
            title={recorder.isSupported ? 'Record voice message' : 'Recording not supported in this browser'}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[8px] border border-line text-ink transition-opacity hover:bg-sunken disabled:opacity-30 dark:border-line-dark dark:text-ink-dark dark:hover:bg-sunken-dark"
          >
            {transcribing ? (
              <CircleNotch size={15} weight="bold" className="animate-spin" />
            ) : (
              <Microphone size={15} weight="fill" />
            )}
          </button>

          <button
            onClick={submit}
            disabled={disabled || !value.trim()}
            aria-label="Send question"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[8px] bg-ink text-paper transition-opacity disabled:opacity-30 dark:bg-ink-dark dark:text-paper-dark"
          >
            <ArrowUp size={15} weight="bold" />
          </button>
        </div>
      )}
    </div>
  )
}
