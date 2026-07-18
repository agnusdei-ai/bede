import { useState, useRef, useCallback } from 'react'
import { convertToWav, getBestMimeType } from '../utils/audioUtils'

/**
 * MediaRecorder hook used for voice enrollment and verification audio capture.
 * Returns WAV blobs ready to POST to the backend.
 */

interface RecordingOptions {
  maxDurationMs?: number
  onComplete?: (wavBlob: Blob) => void
}

// Below this, a recording is almost certainly an accidental micro-tap (a
// misfired press-release, a stray touch) rather than real speech — and
// sending that near-silent sliver to Whisper is worse than skipping it:
// Whisper is documented to hallucinate plausible-looking text (e.g. stock
// phrases) on silence/near-silence rather than returning empty, which would
// otherwise slip past the "only send non-empty transcripts" guard upstream
// and read as a phantom reply with no real question behind it.
const MIN_RECORDING_MS = 400

export function useVoiceRecorder({ maxDurationMs = 6000, onComplete }: RecordingOptions = {}) {
  const [isRecording, setIsRecording] = useState(false)
  const [level, setLevel] = useState(0) // 0–1 volume level for visualisation
  const mediaRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const analyserRef = useRef<AnalyserNode | null>(null)
  const animRef = useRef<number | null>(null)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const startedAtRef = useRef(0)

  const stopRecording = useCallback(async () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current)
    if (animRef.current) cancelAnimationFrame(animRef.current)
    analyserRef.current = null
    setLevel(0)

    const recorder = mediaRef.current
    if (!recorder || recorder.state === 'inactive') return

    const durationMs = Date.now() - startedAtRef.current

    await new Promise<void>((resolve) => {
      recorder.onstop = async () => {
        if (durationMs < MIN_RECORDING_MS) {
          // Too short to be real speech — discard without transcribing.
          resolve()
          return
        }
        const wavBlob = await convertToWav(chunksRef.current)
        onComplete?.(wavBlob)
        resolve()
      }
      recorder.stop()
    })

    recorder.stream.getTracks().forEach((t) => t.stop())
    mediaRef.current = null
    chunksRef.current = []
    setIsRecording(false)
  }, [onComplete])

  const startRecording = useCallback(async () => {
    if (isRecording) return
    chunksRef.current = []

    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true, noiseSuppression: true },
      })
    } catch {
      console.error('Microphone access denied')
      return
    }

    // Volume visualisation via AnalyserNode
    const audioCtx = new AudioContext()
    const source = audioCtx.createMediaStreamSource(stream)
    const analyser = audioCtx.createAnalyser()
    analyser.fftSize = 256
    source.connect(analyser)
    analyserRef.current = analyser

    const dataArray = new Uint8Array(analyser.frequencyBinCount)
    const tick = () => {
      analyser.getByteFrequencyData(dataArray)
      const avg = dataArray.reduce((s, v) => s + v, 0) / dataArray.length
      setLevel(Math.min(1, avg / 128))
      animRef.current = requestAnimationFrame(tick)
    }
    tick()

    const mimeType = getBestMimeType()
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
    recorder.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data) }
    mediaRef.current = recorder
    recorder.start(100) // collect every 100ms
    startedAtRef.current = Date.now()
    setIsRecording(true)

    // Auto-stop at maxDuration
    timeoutRef.current = setTimeout(stopRecording, maxDurationMs)
  }, [isRecording, maxDurationMs, stopRecording])

  return { isRecording, level, startRecording, stopRecording }
}
