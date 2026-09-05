import { useEffect, useState } from 'react'
import { Microphone, PhoneDisconnect, Waveform } from '@phosphor-icons/react'

type VoiceState = 'idle' | 'listening' | 'thinking' | 'speaking'

export function VoiceAgent({ onClose, onAsk }: { onClose: () => void; onAsk: (text: string) => void }) {
  const [state, setState] = useState<VoiceState>('idle')
  const [transcript, setTranscript] = useState('')
  const [agentSpeech, setAgentSpeech] = useState('Hi there! How can I help you today?')

  // Simulated live conversation flow
  useEffect(() => {
    let timer: number
    
    if (state === 'idle') {
      timer = window.setTimeout(() => setState('listening'), 2000)
    } else if (state === 'listening') {
      setTranscript('')
      let i = 0
      const phrase = 'What did we spend on vendor payouts last month?'
      const typingTimer = window.setInterval(() => {
        i++
        setTranscript(phrase.slice(0, i))
        if (i === phrase.length) {
          clearInterval(typingTimer)
          setState('thinking')
        }
      }, 70)
      return () => clearInterval(typingTimer)
    } else if (state === 'thinking') {
      timer = window.setTimeout(() => setState('speaking'), 2000)
    } else if (state === 'speaking') {
      setAgentSpeech('You spent $199,732.46 on vendor payouts in August 2026, across 37 transactions and 12 vendors.')
      timer = window.setTimeout(() => {
        onAsk('What did we spend on vendor payouts last month?')
        onClose()
      }, 5000)
    }

    return () => clearTimeout(timer)
  }, [state, onAsk, onClose])

  return (
    <div className="fixed inset-0 z-[100] flex flex-col bg-paper/95 backdrop-blur-xl dark:bg-paper-dark/95">
      {/* Header */}
      <div className="flex h-20 items-center justify-center p-6">
        <span className="flex items-center gap-2 text-sm font-medium tracking-wide text-ink-muted dark:text-ink-muted-dark uppercase">
          <Waveform size={18} className="animate-pulse text-accent dark:text-accent-dark" />
          Live Voice Session
        </span>
      </div>

      {/* Main Center Area */}
      <div className="flex flex-1 flex-col items-center justify-center p-8">
        {/* Animated Visualizer */}
        <div className="relative mb-16 flex h-48 w-48 items-center justify-center">
          {/* Background Ripples */}
          {state !== 'idle' && (
            <>
              <div className="va-ripple absolute inset-0 rounded-full border-2 border-accent/30 dark:border-accent-dark/30" />
              <div
                className="va-ripple absolute inset-0 rounded-full border-2 border-accent/20 dark:border-accent-dark/20"
                style={{ animationDelay: '0.6s' }}
              />
              <div
                className="va-ripple absolute inset-0 rounded-full border-2 border-accent/10 dark:border-accent-dark/10"
                style={{ animationDelay: '1.2s' }}
              />
            </>
          )}

          {/* Core Orb */}
          <div
            className={`absolute h-32 w-32 rounded-full shadow-[0_0_40px_rgba(15,107,82,0.4)] transition-colors duration-500 dark:shadow-[0_0_40px_rgba(52,199,158,0.4)] ${
              state === 'idle'
                ? 'va-orb-idle bg-accent/20 dark:bg-accent-dark/20'
                : state === 'listening'
                  ? 'va-orb-listening bg-accent/60 dark:bg-accent-dark/60'
                  : state === 'thinking'
                    ? 'va-orb-thinking bg-accent/40 dark:bg-accent-dark/40'
                    : 'va-orb-speaking bg-accent dark:bg-accent-dark'
            }`}
          />
          
          {/* Speaking Waveform (Overlay inside Orb) */}
          {state === 'speaking' && (
            <div className="absolute flex h-16 items-center gap-1.5">
              {[0, 1, 2, 3, 4].map((i) => (
                <span
                  key={i}
                  className="w-1.5 rounded-full bg-paper dark:bg-paper-dark"
                  style={{
                    animation: 'va-waveform 0.8s ease-in-out infinite',
                    animationDelay: `${i * 0.1}s`,
                  }}
                />
              ))}
            </div>
          )}
          {state === 'listening' && (
            <Microphone size={32} weight="fill" className="absolute text-paper dark:text-paper-dark opacity-80" />
          )}
        </div>

        {/* Text Area */}
        <div className="flex h-32 w-full max-w-xl flex-col items-center justify-center space-y-4 text-center">
          {state === 'listening' && (
            <p className="text-2xl font-medium tracking-tight text-ink dark:text-ink-dark">
              {transcript}
              <span className="animate-pulse">|</span>
            </p>
          )}
          {state === 'thinking' && (
            <p className="text-xl italic text-ink-muted dark:text-ink-muted-dark">Thinking...</p>
          )}
          {(state === 'speaking' || state === 'idle') && (
            <p className="text-2xl font-medium tracking-tight text-ink dark:text-ink-dark">
              {agentSpeech}
            </p>
          )}
        </div>
      </div>

      {/* Footer Controls */}
      <div className="flex h-32 items-center justify-center pb-8">
        <button
          onClick={onClose}
          className="flex h-16 w-16 items-center justify-center rounded-full bg-brick text-paper shadow-xl transition-transform hover:scale-105 active:scale-95 dark:bg-brick-dark dark:text-paper-dark"
          aria-label="End Call"
          title="End Call"
        >
          <PhoneDisconnect size={28} weight="fill" />
        </button>
      </div>
    </div>
  )
}
