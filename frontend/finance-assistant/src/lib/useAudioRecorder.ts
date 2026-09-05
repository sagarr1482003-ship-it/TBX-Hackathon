/**
 * ChatGPT-style audio recording hook built on the MediaRecorder API.
 *
 * Flow: start() asks for mic permission and begins capturing. stop() resolves
 * with the recorded audio as a single Blob (webm/opus where supported, else the
 * browser default). The hook also exposes a live `seconds` timer and an
 * `amplitude` (0..1) sampled from an AnalyserNode so callers can animate a
 * waveform / pulsing mic while recording.
 */

import { useCallback, useRef, useState } from 'react'

export type RecorderStatus = 'idle' | 'recording' | 'stopping'

export interface UseAudioRecorder {
  status: RecorderStatus
  seconds: number
  amplitude: number
  error: string | null
  isSupported: boolean
  start: () => Promise<void>
  stop: () => Promise<Blob | null>
  cancel: () => void
}

function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === 'undefined') return undefined
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg']
  for (const type of candidates) {
    if (MediaRecorder.isTypeSupported?.(type)) return type
  }
  return undefined
}

export function useAudioRecorder(): UseAudioRecorder {
  const [status, setStatus] = useState<RecorderStatus>('idle')
  const [seconds, setSeconds] = useState(0)
  const [amplitude, setAmplitude] = useState(0)
  const [error, setError] = useState<string | null>(null)

  const recorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const timerRef = useRef<number | null>(null)
  const rafRef = useRef<number | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)

  const isSupported =
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof MediaRecorder !== 'undefined'

  const cleanup = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current)
      timerRef.current = null
    }
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    analyserRef.current = null
    if (audioCtxRef.current && audioCtxRef.current.state !== 'closed') {
      void audioCtxRef.current.close()
    }
    audioCtxRef.current = null
    recorderRef.current = null
    setAmplitude(0)
  }, [])

  const start = useCallback(async () => {
    if (!isSupported) {
      setError('Recording is not supported in this browser.')
      return
    }
    setError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      chunksRef.current = []

      const mimeType = pickMimeType()
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
      recorderRef.current = recorder
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data)
      }
      recorder.start()

      // Live level metering for the waveform animation.
      try {
        const AudioCtx =
          window.AudioContext ??
          (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
        if (AudioCtx) {
          const ctx = new AudioCtx()
          audioCtxRef.current = ctx
          const source = ctx.createMediaStreamSource(stream)
          const analyser = ctx.createAnalyser()
          analyser.fftSize = 256
          source.connect(analyser)
          analyserRef.current = analyser
          const data = new Uint8Array(analyser.frequencyBinCount)
          const sample = () => {
            analyser.getByteTimeDomainData(data)
            let sum = 0
            for (let i = 0; i < data.length; i++) {
              const v = (data[i] - 128) / 128
              sum += v * v
            }
            const rms = Math.sqrt(sum / data.length)
            setAmplitude(Math.min(1, rms * 3))
            rafRef.current = requestAnimationFrame(sample)
          }
          rafRef.current = requestAnimationFrame(sample)
        }
      } catch {
        // Metering is best-effort; recording still works without it.
      }

      setSeconds(0)
      setStatus('recording')
      timerRef.current = window.setInterval(() => setSeconds((s) => s + 1), 1000)
    } catch (err) {
      cleanup()
      setStatus('idle')
      const name = err instanceof DOMException ? err.name : ''
      setError(
        name === 'NotAllowedError' || name === 'SecurityError'
          ? 'Microphone access was denied.'
          : 'Could not start recording.',
      )
    }
  }, [isSupported, cleanup])

  const stop = useCallback((): Promise<Blob | null> => {
    const recorder = recorderRef.current
    if (!recorder || recorder.state === 'inactive') {
      cleanup()
      setStatus('idle')
      return Promise.resolve(null)
    }
    setStatus('stopping')
    return new Promise<Blob | null>((resolve) => {
      recorder.onstop = () => {
        const type = recorder.mimeType || 'audio/webm'
        const blob = chunksRef.current.length ? new Blob(chunksRef.current, { type }) : null
        chunksRef.current = []
        cleanup()
        setStatus('idle')
        resolve(blob)
      }
      recorder.stop()
    })
  }, [cleanup])

  const cancel = useCallback(() => {
    const recorder = recorderRef.current
    if (recorder && recorder.state !== 'inactive') {
      recorder.onstop = null
      try {
        recorder.stop()
      } catch {
        /* noop */
      }
    }
    chunksRef.current = []
    cleanup()
    setStatus('idle')
  }, [cleanup])

  return { status, seconds, amplitude, error, isSupported, start, stop, cancel }
}
