// Mirror of homeschool-tutor/src/hooks/useVoiceRecorder.ts for the demo app.
import { useState, useRef, useCallback } from 'react'
import { resample, encodeWav } from './audioUtils'

/**
 * Raw-PCM capture hook used for voice enrollment and verification audio
 * capture. Returns WAV blobs ready to POST to the backend.
 *
 * This taps raw PCM samples directly off the live microphone audio graph
 * (via a ScriptProcessorNode, at the same tap point the level-meter
 * AnalyserNode already uses below) instead of recording through
 * MediaRecorder and decoding the result afterwards. That encode/decode
 * round trip (MediaRecorder → Blob → AudioContext.decodeAudioData) is a
 * documented source of failures specifically on iOS Safari, which can fail
 * to decode its own MediaRecorder-produced MP4/AAC output — silently, with
 * the failure surfacing as an unhandled promise rejection that left
 * stopRecording() hanging forever and nothing ever shown to the user.
 * Capturing PCM directly sidesteps that whole compatibility surface: there
 * is no container or codec to decode, on any browser.
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

// 4096 samples per callback is the MediaRecorder-era default and comfortably
// supported everywhere ScriptProcessorNode still runs (deprecated but not
// removed in any current browser, including iOS Safari).
const PROCESSOR_BUFFER_SIZE = 4096

export function useVoiceRecorder({ maxDurationMs = 6000, onComplete }: RecordingOptions = {}) {
  const [isRecording, setIsRecording] = useState(false)
  const [level, setLevel] = useState(0) // 0–1 volume level for visualisation
  const audioCtxRef = useRef<AudioContext | null>(null)
  const processorRef = useRef<ScriptProcessorNode | null>(null)
  const silenceRef = useRef<GainNode | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const pcmChunksRef = useRef<Float32Array[]>([])
  const analyserRef = useRef<AnalyserNode | null>(null)
  const animRef = useRef<number | null>(null)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const startedAtRef = useRef(0)
  // A getUserMedia() call opened synchronously inside a user gesture (a
  // press/tap handler), stashed here so startRecording() below can reuse it
  // even when IT runs much later, outside any gesture — see prewarm().
  const prewarmStreamRef = useRef<MediaStream | null>(null)
  const prewarmPromiseRef = useRef<Promise<MediaStream | null> | null>(null)

  const getStream = useCallback((constraints: MediaStreamConstraints['audio']) =>
    navigator.mediaDevices
      .getUserMedia({ audio: constraints })
      .catch((): MediaStream | null => {
        console.error('Microphone access denied')
        return null
      })
  , [])

  const MIC_CONSTRAINTS = {
    sampleRate: 16000,
    channelCount: 1,
    echoCancellation: true,
    noiseSuppression: true,
  }

  // iOS Safari only honors getUserMedia() when it's *initiated* directly
  // inside a user gesture's call stack — a call made from a later timer
  // callback (e.g. the hybrid hook's native-recognition stall watchdog,
  // which only fires seconds after the press) is a documented case Safari
  // silently blocks, with the returned promise rejecting (or, worse, just
  // never settling) and no visible error. That leaves the recorder's mode
  // stuck at "recording" forever with nothing ever captured — the same
  // "stuck listening, nothing transcribed" symptom the fallback exists to
  // fix in the first place, just moved one layer deeper.
  //
  // The fix: call getUserMedia() here, synchronously, at the moment of the
  // press — BEFORE it's known whether the fallback will even be needed —
  // so the request is always inside the gesture's call chain. startRecording
  // below then reuses whatever this resolves to (or falls back to a fresh,
  // synchronous call itself, for callers that invoke it directly from a
  // press handler with no separate prewarm step).
  const prewarm = useCallback(() => {
    if (prewarmPromiseRef.current) return prewarmPromiseRef.current
    const p = getStream(MIC_CONSTRAINTS).then((stream) => {
      prewarmStreamRef.current = stream
      return stream
    })
    prewarmPromiseRef.current = p
    return p
  }, [getStream])

  // Releases a prewarmed stream that ended up unused — e.g. native speech
  // recognition worked fine, so the recorder fallback was never actually
  // started. Without this the mic stays open (and any "microphone in use"
  // indicator stays lit) for the rest of the press for no reason.
  const cancelPrewarm = useCallback(() => {
    const pending = prewarmPromiseRef.current
    prewarmStreamRef.current = null
    prewarmPromiseRef.current = null
    pending?.then((stream) => {
      if (stream && stream !== streamRef.current) {
        stream.getTracks().forEach((t) => t.stop())
      }
    })
  }, [])

  const stopRecording = useCallback(async () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current)
    if (animRef.current) cancelAnimationFrame(animRef.current)
    analyserRef.current = null
    setLevel(0)

    const processor = processorRef.current
    const audioCtx = audioCtxRef.current
    const stream = streamRef.current
    if (!processor || !audioCtx || !stream) {
      setIsRecording(false)
      return
    }

    const durationMs = Date.now() - startedAtRef.current

    processor.onaudioprocess = null
    processor.disconnect()
    silenceRef.current?.disconnect()
    const nativeSampleRate = audioCtx.sampleRate
    // Safe even if already closed elsewhere — close() on a closed context
    // rejects, which would otherwise become an unhandled rejection here.
    try {
      await audioCtx.close()
    } catch {
      // already closed — nothing to do
    }
    stream.getTracks().forEach((t) => t.stop())

    processorRef.current = null
    silenceRef.current = null
    audioCtxRef.current = null
    streamRef.current = null
    setIsRecording(false)

    const chunks = pcmChunksRef.current
    pcmChunksRef.current = []

    if (durationMs < MIN_RECORDING_MS) {
      // Too short to be real speech — discard without transcribing.
      return
    }

    const totalLength = chunks.reduce((sum, chunk) => sum + chunk.length, 0)
    const merged = new Float32Array(totalLength)
    let offset = 0
    for (const chunk of chunks) {
      merged.set(chunk, offset)
      offset += chunk.length
    }

    const samples = nativeSampleRate === 16000 ? merged : resample(merged, nativeSampleRate, 16000)
    const wavBuffer = encodeWav(samples, 16000)
    const wavBlob = new Blob([wavBuffer], { type: 'audio/wav' })
    onComplete?.(wavBlob)
  }, [onComplete])

  const startRecording = useCallback(async () => {
    if (isRecording) return
    pcmChunksRef.current = []

    // Reuse a stream prewarm() already opened synchronously inside the
    // user's press gesture when one is in flight/ready. Only call
    // getUserMedia() fresh here as a fallback for callers that invoke
    // startRecording() directly from their own press handler (still inside
    // a gesture at that point, so a cold call here is still safe) — see
    // prewarm() above for why a cold call from anywhere else is not.
    const pending = prewarmPromiseRef.current ?? getStream(MIC_CONSTRAINTS)
    prewarmPromiseRef.current = null
    const stream = prewarmStreamRef.current ?? (await pending)
    prewarmStreamRef.current = null
    if (!stream) return

    const audioCtx = new AudioContext()
    audioCtxRef.current = audioCtx
    const source = audioCtx.createMediaStreamSource(stream)

    // Volume visualisation via AnalyserNode (unchanged).
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

    // Raw PCM capture. ScriptProcessorNode only fires onaudioprocess while
    // connected into a live graph that reaches a destination — route it
    // through a zero-gain node so nothing is audibly played back (no mic
    // monitoring/echo) while still keeping the processor "pulled".
    const processor = audioCtx.createScriptProcessor(PROCESSOR_BUFFER_SIZE, 1, 1)
    processor.onaudioprocess = (e) => {
      pcmChunksRef.current.push(new Float32Array(e.inputBuffer.getChannelData(0)))
    }
    source.connect(processor)
    const silence = audioCtx.createGain()
    silence.gain.value = 0
    processor.connect(silence)
    silence.connect(audioCtx.destination)
    processorRef.current = processor
    silenceRef.current = silence

    streamRef.current = stream
    startedAtRef.current = Date.now()
    setIsRecording(true)

    // Auto-stop at maxDuration
    timeoutRef.current = setTimeout(stopRecording, maxDurationMs)
  }, [isRecording, maxDurationMs, stopRecording, getStream])

  return { isRecording, level, startRecording, stopRecording, prewarm, cancelPrewarm }
}
