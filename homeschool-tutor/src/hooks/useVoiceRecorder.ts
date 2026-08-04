// Mirror of demo/src/useVoiceRecorder.ts for the homeschool-tutor app.
import { useState, useRef, useCallback } from 'react'
import { resample, encodeWav, encodePcm16 } from '../utils/audioUtils'
import { logDebug } from './debugBus'

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

/** 'permission-denied' when the browser/OS blocked the mic (or the child
 *  dismissed the prompt); 'unavailable' for anything else getUserMedia can
 *  fail with (no device, hardware in use, insecure context, ...). */
export type MicErrorReason = 'permission-denied' | 'unavailable'

/** Shared by stopRecording() (the final encode) and snapshotWav() (a
 *  non-destructive mid-recording peek for the streaming-transcription
 *  chunk-upload loop — see useHybridVoiceInput.ts) — merges captured PCM
 *  chunks, resamples to 16kHz if needed, and encodes to a WAV blob. */
function _encodeChunksToWav(chunks: Float32Array[], nativeSampleRate: number): Blob {
  const totalLength = chunks.reduce((sum, chunk) => sum + chunk.length, 0)
  const merged = new Float32Array(totalLength)
  let offset = 0
  for (const chunk of chunks) {
    merged.set(chunk, offset)
    offset += chunk.length
  }
  const samples = nativeSampleRate === 16000 ? merged : resample(merged, nativeSampleRate, 16000)
  const wavBuffer = encodeWav(samples, 16000)
  return new Blob([wavBuffer], { type: 'audio/wav' })
}

interface RecordingOptions {
  maxDurationMs?: number
  onComplete?: (wavBlob: Blob) => void
  /** Fired whenever getUserMedia() rejects — the only signal that a press
   *  is about to silently do nothing (see startRecording's `if (!stream)
   *  return` below, which has no other way to tell the caller). */
  onError?: (reason: MicErrorReason) => void
  /** Fired the moment recording is genuinely underway (the audio graph is
   *  live) — lets a caller-side "did this even start" safety timeout clear
   *  itself instead of running for its full fixed duration against a real,
   *  in-progress hold. See useHybridVoiceInput.ts's RECORDING_SAFETY_TIMEOUT_MS. */
  onStarted?: () => void
  /** Fired at the end of every stopRecording() call, regardless of outcome
   *  (produced a blob, discarded as too short, or had nothing to stop) —
   *  the one reliable "this recording is now fully finished" signal, unlike
   *  onComplete which only fires when there's audio worth transcribing. */
  onStopped?: () => void
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

export function useVoiceRecorder({ maxDurationMs = 6000, onComplete, onError, onStarted, onStopped }: RecordingOptions = {}) {
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
  // True from the instant startRecording() is entered until the recording is
  // fully torn down — including the async window while getUserMedia() is
  // still in flight, which the `isRecording` STATE below cannot cover (it
  // only flips true once the audio graph is actually live, several hundred
  // milliseconds later). Guarding on the state instead had two failure modes,
  // both seen in a real debug-panel trace: two presses inside that window
  // opened two independent audio graphs, and — far worse — a state update
  // that never landed left `isRecording` stuck true, which made the
  // `if (isRecording) return` guard reject every subsequent press for the
  // rest of the session, so the mic button silently stopped working with
  // nothing on screen explaining why.
  const activeRef = useRef(false)
  // Bumped by every stopRecording(). startRecording() captures it before
  // awaiting getUserMedia() and re-checks afterwards, so a turn that ended
  // while the mic was still opening can tear the just-granted stream down
  // instead of building a live graph nobody is tracking. That orphaned graph
  // was the actual cause of the stuck-`isRecording` case above: the OS
  // recording indicator stayed lit while the app believed it was idle.
  const runGenRef = useRef(0)

  const getStream = useCallback((constraints: MediaStreamConstraints['audio']) =>
    navigator.mediaDevices
      .getUserMedia({ audio: constraints })
      .catch((err: unknown): MediaStream | null => {
        console.error('Microphone access denied', err)
        const name = err instanceof DOMException ? err.name : ''
        // Also on-screen (logDebug), not just the browser console — the
        // console.error above is invisible in a DebugOverlay screenshot,
        // which is the only trace a remote user can actually send us. This
        // is the one line that reveals WHICH getUserMedia failure occurred
        // (NotReadableError/device-in-use vs. NotFoundError vs. genuine
        // permission denial), which the reason classification below throws away.
        logDebug(`getStream() rejected name=${name || 'unknown'} message=${err instanceof Error ? err.message : String(err)}`)
        const reason: MicErrorReason = name === 'NotAllowedError' || name === 'PermissionDeniedError' ? 'permission-denied' : 'unavailable'
        onError?.(reason)
        return null
      })
  , [onError])

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
    logDebug('useVoiceRecorder.stopRecording()')
    // Both SYNCHRONOUSLY and first, before anything below can await: this is
    // what a startRecording() still waiting on getUserMedia() checks to learn
    // its turn is already over, and what lets the very next press start a
    // fresh recording even when this call takes the early return below.
    runGenRef.current += 1
    activeRef.current = false
    if (timeoutRef.current) clearTimeout(timeoutRef.current)
    if (animRef.current) cancelAnimationFrame(animRef.current)
    analyserRef.current = null
    setLevel(0)

    const processor = processorRef.current
    const audioCtx = audioCtxRef.current
    const stream = streamRef.current
    const silence = silenceRef.current
    if (!processor || !audioCtx || !stream) {
      setIsRecording(false)
      onStopped?.()
      return
    }

    // Null every ref out SYNCHRONOUSLY, right here — before the `await
    // audioCtx.close()` below — not after it. A held mic button can get
    // released twice for one press on iOS Safari (e.g. release() firing
    // again while this call is still awaiting close()), and stopRecording()
    // used to leave these refs populated across that whole await. A second
    // concurrent call would then read the SAME non-null refs, pass this same
    // guard, and re-process the SAME pcmChunksRef chunks — producing a
    // byte-identical second WAV that gets transcribed and sent again,
    // showing up as the exact turn appearing twice in the chat. Clearing the
    // refs up front means a second call sees them already null and takes
    // the early-return above instead of racing to do this all twice.
    processorRef.current = null
    silenceRef.current = null
    audioCtxRef.current = null
    streamRef.current = null

    const durationMs = Date.now() - startedAtRef.current

    processor.onaudioprocess = null
    processor.disconnect()
    silence?.disconnect()
    const nativeSampleRate = audioCtx.sampleRate
    // Safe even if already closed elsewhere — close() on a closed context
    // rejects, which would otherwise become an unhandled rejection here.
    try {
      await audioCtx.close()
    } catch {
      // already closed — nothing to do
    }
    stream.getTracks().forEach((t) => t.stop())

    setIsRecording(false)

    const chunks = pcmChunksRef.current
    pcmChunksRef.current = []
    uploadedChunksRef.current = 0

    if (durationMs < MIN_RECORDING_MS) {
      // Too short to be real speech — discard without transcribing. Still
      // notify onStopped: a real reported bug had this early return leave
      // the CALLER's own mode stuck at "recording" forever (onComplete,
      // the only signal the caller otherwise had, never fires here), with
      // nothing to recover it short of a much-later safety timeout.
      onStopped?.()
      return
    }

    const wavBlob = _encodeChunksToWav(chunks, nativeSampleRate)
    onComplete?.(wavBlob)
    onStopped?.()
  }, [onComplete, onStopped])

  const startRecording = useCallback(async () => {
    if (activeRef.current) return
    activeRef.current = true
    const gen = runGenRef.current
    logDebug('useVoiceRecorder.startRecording()')
    pcmChunksRef.current = []

    // Reuse a stream prewarm() already opened synchronously inside the
    // user's press gesture when one is in flight/ready. Only call
    // getUserMedia() fresh here as a fallback for callers that invoke
    // startRecording() directly from their own press handler (still inside
    // a gesture at that point, so a cold call here is still safe) — see
    // prewarm() above for why a cold call from anywhere else is not.
    const pending = prewarmPromiseRef.current ?? getStream(MIC_CONSTRAINTS)
    prewarmPromiseRef.current = null
    let stream = prewarmStreamRef.current ?? (await pending)
    prewarmStreamRef.current = null
    if (!stream) {
      // The prewarmed stream can fail from mic contention with whatever
      // else grabbed the microphone right at the start of the press (most
      // often native Web Speech Recognition's own internal capture) — a
      // transient race, not a real "no mic available" situation. By the
      // time the fallback is actually needed (native has stalled for
      // NATIVE_STALL_TIMEOUT_MS and native.stop() has already run), that
      // contention is gone, so a fresh getUserMedia() call here often
      // succeeds even though the prewarm attempt didn't. Confirmed via a
      // real debug-panel trace: the prewarm failure never even reached
      // onError (mode was still 'native' when it rejected, so the guard in
      // useHybridVoiceInput correctly ignored it) but the fallback then
      // silently gave up on that same stale, already-failed promise instead
      // of trying again — turning a one-off race into a hard failure.
      logDebug('startRecording(): prewarmed stream unavailable — retrying getUserMedia() fresh')
      stream = await getStream(MIC_CONSTRAINTS)
    }
    if (!stream) {
      // getUserMedia failed for good (onError has already fired). Release the
      // guard so the next press is a real retry rather than a no-op — but
      // only if this is still the current turn, since a later press may
      // already have claimed the guard while this one was failing.
      if (runGenRef.current === gen) activeRef.current = false
      return
    }
    if (runGenRef.current !== gen) {
      // The turn ended while the mic was still opening — stopRecording() has
      // already run and found nothing to tear down. Building the graph now
      // would leave the microphone live with no owner, so hand the stream
      // straight back instead. activeRef was cleared by that stopRecording().
      logDebug('startRecording(): cancelled while the mic was opening — releasing the stream')
      stream.getTracks().forEach((t) => t.stop())
      return
    }

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
    onStarted?.()

    // Auto-stop at maxDuration
    timeoutRef.current = setTimeout(stopRecording, maxDurationMs)
    // `isRecording` is deliberately NOT a dependency any more — the guard at
    // the top reads activeRef instead, so this callback no longer needs to be
    // rebuilt on every recording state change (and can no longer capture a
    // stale copy of it).
  }, [maxDurationMs, stopRecording, getStream, onStarted])

  // Non-destructive: does NOT clear pcmChunksRef the way stopRecording()
  // does, since the caller (the streaming-transcription chunk-upload loop)
  // always wants everything captured so far, not a delta since the last
  // snapshot — matching how the server always re-transcribes the whole
  // growing buffer too. Returns null before the audio graph is actually up
  // (audioCtxRef not yet set, or nothing captured yet).
  // How many captured chunks the streaming-transcription loop has already
  // uploaded. snapshotPcmDelta() below reads from here forward, so a long
  // hold uploads each second of audio exactly once instead of re-sending the
  // whole recording on every tick — that used to cost 8.3MB of upload for a
  // 40-second answer, and 63MB at the 120s safety cap.
  const uploadedChunksRef = useRef(0)

  /** Raw int16 PCM for everything captured since the last call, advancing the
   *  cursor. Returns null when nothing new has arrived. Non-destructive with
   *  respect to the buffer itself: stopRecording()'s final encode still sees
   *  every chunk, so the delta cursor can never cost us the real recording. */
  const snapshotPcmDelta = useCallback((): Blob | null => {
    const ctx = audioCtxRef.current
    if (!ctx) return null
    const fresh = pcmChunksRef.current.slice(uploadedChunksRef.current)
    if (!fresh.length) return null
    uploadedChunksRef.current = pcmChunksRef.current.length

    const total = fresh.reduce((sum, c) => sum + c.length, 0)
    const merged = new Float32Array(total)
    let offset = 0
    for (const chunk of fresh) { merged.set(chunk, offset); offset += chunk.length }
    const samples = ctx.sampleRate === 16000 ? merged : resample(merged, ctx.sampleRate, 16000)
    return new Blob([encodePcm16(samples)], { type: 'application/octet-stream' })
  }, [])

  const snapshotWav = useCallback((): Blob | null => {
    if (!audioCtxRef.current || pcmChunksRef.current.length === 0) return null
    return _encodeChunksToWav(pcmChunksRef.current, audioCtxRef.current.sampleRate)
  }, [])

  return { isRecording, level, startRecording, stopRecording, snapshotWav, snapshotPcmDelta, prewarm, cancelPrewarm }
}
