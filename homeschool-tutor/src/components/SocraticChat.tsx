import { useState, useRef, useEffect, useCallback } from 'react'
import { Send, Loader2, Mic, MicOff, Volume2, VolumeX, PenLine, FileUp, X, Sparkles } from 'lucide-react'
import { streamTutorChat, updateVoiceNarrationPreference, extractNarrationText } from '../services/api'
import { getApiMessages, useSessionStore } from '../store/sessionStore'
import { useHybridVoiceInput } from '../hooks/useHybridVoiceInput'
import { useTextToSpeech } from '../hooks/useTextToSpeech'
import { useChatTheme } from '../hooks/useChatTheme'
import { isDuplicateUtterance } from '../utils/dedupe'
import { renderEmphasis } from '../utils/renderEmphasis'
import HandwritingCanvas from './HandwritingCanvas'
import VisualAidCard from './VisualAidCard'

// How long Bede waits, in silence, after a turn ends before gently picking
// the thread back up (the [CONTINUE] sentinel — see ai_service.py's rule
// on it) rather than leaving the child sitting in dead air indefinitely.
// Capped at MAX_CONSECUTIVE_CONTINUES in a row so this can't loop forever
// talking to itself if the child has actually walked away — it resets the
// moment they send a real response or a new subject opener fires. Mirrors
// demo/src/App.tsx's IDLE_CONTINUE_MS/MAX_CONSECUTIVE_AUTO_CONTINUES.
const INACTIVITY_TIMEOUT_MS = 60_000
const MAX_CONSECUTIVE_CONTINUES = 2

export default function SocraticChat({ breakActive = false, gradeStage }: { breakActive?: boolean; gradeStage?: string }) {
  const [input, setInput] = useState('')
  const [showCanvas, setShowCanvas] = useState(false)
  const { bubble } = useChatTheme()
  const [pendingDrawing, setPendingDrawing] = useState<string | null>(null)
  const [uploadingNarration, setUploadingNarration] = useState(false)
  const narrationFileInputRef = useRef<HTMLInputElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const advanceSubjectRef = useRef(false)  // set when Bede signals mastery/frustration mid-stream
  const inactivityTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const consecutiveContinuesRef = useRef(0)
  // Mirrors `input` for the inactivity timer's callback, which reads it at
  // fire time rather than closing over it — avoids re-arming the timer on
  // every keystroke while still correctly skipping a child mid-typing.
  const inputRef = useRef('')
  useEffect(() => { inputRef.current = input }, [input])

  // ── Voice command mode ────────────────────────────────────────────────────
  // Tapping the mic used to just drop the transcript into the text box,
  // leaving the child to then manually hit Send — an awkward extra step for
  // a voice-first interaction. While voice mode is on, a finished transcript
  // sends itself immediately, and once Bede's reply (text + any spoken
  // narration) finishes, the mic re-activates on its own — a hands-free
  // loop until the child taps the mic again to turn it off. Typing, Send,
  // drawing, and file upload all keep working normally alongside it; voice
  // mode only changes what the mic button itself does.
  const [voiceMode, setVoiceMode] = useState(false)
  const voiceModeRef = useRef(false)
  useEffect(() => { voiceModeRef.current = voiceMode }, [voiceMode])
  // Tracks whether a turn (streaming and/or Bede's spoken reply) is in
  // flight, so the effect below can detect the moment it fully ends —
  // see its own comment for why this needs both isStreaming and isSpeaking.
  const turnActiveRef = useRef(false)

  const {
    token,
    sessionConfig,
    currentSubject,
    subjectStart,
    displayMessages,
    isStreaming,
    timeOfDay,
    startAssistantStream,
    addUserMessage,
    appendAssistantChunk,
    addToolMessage,
    addVisualAidMessage,
    finalizeAssistantMessage,
    setStreaming,
    nextSubject,
    setSessionConfig,
  } = useSessionStore()

  // ── Text-to-speech: Bede speaks its responses ────────────────────────────
  const {
    speak, stop: stopSpeech, toggle: toggleTTSLocal, isSpeaking,
    enabled: ttsEnabled, isSupported: ttsSupported,
  } = useTextToSpeech(token, sessionConfig?.voice_narration_enabled ?? true)

  // Wraps the local toggle to also persist the child's choice server-side,
  // so it's remembered next session (see api.ts's updateVoiceNarrationPreference).
  const toggleTTS = useCallback(() => {
    const newValue = !ttsEnabled
    toggleTTSLocal()
    if (sessionConfig) {
      setSessionConfig({ ...sessionConfig, voice_narration_enabled: newValue })
      if (token) {
        updateVoiceNarrationPreference(token, sessionConfig.student_name, newValue).catch(() => {
          // Best-effort — a failed save shouldn't interrupt the session the
          // child is already in; it just won't be remembered next time.
        })
      }
    }
  }, [ttsEnabled, toggleTTSLocal, sessionConfig, setSessionConfig, token])

  // ── Speech recognition: child speaks instead of typing ──────────────────
  // Native Web Speech API first, auto-falls back to recording + server-side
  // Whisper transcription when it's unsupported, errors, or silently stalls
  // (Safari/iOS are known to do this — see useHybridVoiceInput).
  const { isListening, isTranscribing, interim, isSupported: sttSupported, start: startListening, stop: stopListening } = useHybridVoiceInput({
    token,
    onFinal: (transcript) => {
      if (voiceModeRef.current) {
        send(transcript)
      } else {
        setInput((prev) => (prev ? prev + ' ' + transcript : transcript))
      }
    },
  })

  // Track which subjects have already received their opening message
  const openerFiredRef = useRef(new Set<string>())

  const clearInactivityTimer = useCallback(() => {
    if (inactivityTimerRef.current) clearTimeout(inactivityTimerRef.current)
    inactivityTimerRef.current = null
  }, [])

  // Shared by sendOpener/send/sendContinue below — each just sets up the
  // request differently (history, message text, whether a user bubble gets
  // added), then hands the resulting stream here. Speaks the whole turn as
  // ONE synthesis call, not one call per chunk: separate independently-
  // synthesized clips (main text, then each tool card) stitched together
  // with a network round-trip gap between them read as choppy and
  // mechanical even when each clip's own voice quality is fine — a single
  // continuous take sounds like one person talking.
  const consumeTurnStream = useCallback(async (stream: ReturnType<typeof streamTutorChat>) => {
    const speechSegments: string[] = []
    let pendingText = ''
    // Everything this turn has already said (text + rendered cards) — the
    // duplicate-suppression reference for isDuplicateUtterance below.
    let turnText = ''
    const flush = () => {
      if (pendingText.trim()) speechSegments.push(pendingText)
      pendingText = ''
    }
    try {
      for await (const chunk of stream) {
        if (chunk.type === 'text' && chunk.content) {
          appendAssistantChunk(chunk.content)
          pendingText += chunk.content
          turnText += chunk.content
        } else if (chunk.type === 'tool' && chunk.content) {
          flush()
          // Side effects (opening the canvas) still fire even for a card we
          // suppress — only the duplicated words are dropped, not the action.
          if (chunk.tool === 'invite_handwriting') setShowCanvas(true)
          if (isDuplicateUtterance(chunk.content, turnText)) {
            // The turn already said this — don't render or speak it twice.
            continue
          }
          addToolMessage(chunk.tool ?? 'tool', chunk.content)
          speechSegments.push(chunk.content)
          turnText += ' ' + chunk.content
        } else if (chunk.type === 'assessment') {
          // Silent server-side narration score — no UI change for child
        } else if (chunk.type === 'visual_aid' && chunk.visualAid) {
          addVisualAidMessage(chunk.visualAid)
        } else if (chunk.type === 'subject_complete') {
          flush()
          addToolMessage('subject_complete', chunk.content ?? "Let's move on to our next subject!")
          speechSegments.push(chunk.content ?? '')
          advanceSubjectRef.current = true
        } else if (chunk.type === 'done') {
          break
        }
      }
      flush()
      if (speechSegments.length) speak(speechSegments.join(' '))
    } catch (err: unknown) {
      if (err instanceof Error && err.name !== 'AbortError') {
        addToolMessage('error', `⚠️ ${err.message}`)
      }
    } finally {
      finalizeAssistantMessage()
      setStreaming(false)
      // advanceSubjectRef, if set, is picked up by the turn-completion effect
      // below once streaming AND any queued speech have both finished.
    }
  }, [appendAssistantChunk, addToolMessage, addVisualAidMessage, finalizeAssistantMessage, setStreaming, speak])

  // sendOpener reads live store state to avoid stale-closure issues during streaming
  const sendOpener = useCallback(async () => {
    const state = useSessionStore.getState()
    if (state.isStreaming || !state.token || !state.sessionConfig) return

    // Cuts off any speech still playing/queued from the PREVIOUS subject
    // before this one starts. isStreaming above guards against overlapping
    // FETCHES, but speak() below isn't awaited by the turn that queued it —
    // isStreaming goes back to false as soon as the stream finishes reading,
    // well before its queued audio has actually finished playing — so
    // without this, a subject switch can leave the old subject's narration
    // playing (or queued right behind) the new subject's opener.
    stopSpeech()
    stopListening()

    state.startAssistantStream()
    abortRef.current?.abort()
    abortRef.current = new AbortController()

    const stream = streamTutorChat(
      state.token,
      state.sessionConfig,
      state.currentSubject,
      [],          // no prior history — clean slate for each subject opener
      '[START]',
      abortRef.current.signal,
      undefined,
      state.timeOfDay,
    )
    await consumeTurnStream(stream)
  }, [consumeTurnStream, stopSpeech, stopListening])

  // Fires after the child has gone quiet for INACTIVITY_TIMEOUT_MS following
  // Bede's last turn — sends the [CONTINUE] sentinel (see ai_service.py's
  // rule 11) so Bede gently picks the thread back up instead of the session
  // just sitting in dead air until the child happens to speak or type.
  // Silent by design, same as the opener: no user bubble, no mention of the
  // pause on Bede's end either (that's the backend's job).
  const sendContinue = useCallback(async () => {
    const state = useSessionStore.getState()
    if (state.isStreaming || !state.token || !state.sessionConfig) return
    // Don't interrupt a child who's mid-drawing, has a drawing ready to
    // send, is uploading narration, or has unsent text sitting in the box —
    // the whole point is to fire only once they've genuinely gone quiet.
    if (showCanvas || pendingDrawing || uploadingNarration || inputRef.current.trim()) return
    if (consecutiveContinuesRef.current >= MAX_CONSECUTIVE_CONTINUES) return
    consecutiveContinuesRef.current += 1

    stopSpeech()
    stopListening()

    const apiHistory = getApiMessages(state.displayMessages, state.subjectStart)
    state.startAssistantStream()
    abortRef.current?.abort()
    abortRef.current = new AbortController()

    const stream = streamTutorChat(
      state.token,
      state.sessionConfig,
      state.currentSubject,
      apiHistory,
      '[CONTINUE]',
      abortRef.current.signal,
      undefined,
      state.timeOfDay,
    )
    await consumeTurnStream(stream)
  }, [consumeTurnStream, stopSpeech, stopListening, showCanvas, pendingDrawing, uploadingNarration])

  // Fire opener once per subject — when subject changes and session is ready
  useEffect(() => {
    if (!sessionConfig || !token) return
    if (openerFiredRef.current.has(currentSubject)) return
    openerFiredRef.current.add(currentSubject)
    consecutiveContinuesRef.current = 0  // fresh subject, fresh idle-continue budget
    sendOpener()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentSubject, !!sessionConfig, !!token])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [displayMessages])

  const handleDrawingSubmit = (imageDataUrl: string) => {
    setPendingDrawing(imageDataUrl)
    setShowCanvas(false)
  }
  const handleDrawingCancel = () => setShowCanvas(false)

  const send = useCallback(async (overrideMsg?: string) => {
    // overrideMsg lets voice mode's onFinal send a transcript directly,
    // without a setInput()-then-read round trip through React state.
    const msg = (overrideMsg ?? input).trim()
    if ((!msg && !pendingDrawing) || isStreaming || !token || !sessionConfig) return

    stopSpeech()      // stop any ongoing speech when child replies
    stopListening()
    setInput('')
    consecutiveContinuesRef.current = 0  // a real response — the idle-continue cap starts fresh

    // Append drawing indicator to message if a drawing is pending
    const fullMsg = pendingDrawing ? msg + (msg ? ' ' : '') + '[✏️ Drawing]' : msg
    const drawingToSend = pendingDrawing
    setPendingDrawing(null)

    // Snapshot current-subject history BEFORE addUserMessage mutates displayMessages
    const apiHistory = getApiMessages(displayMessages, subjectStart)
    addUserMessage(fullMsg)

    abortRef.current?.abort()
    abortRef.current = new AbortController()

    const stream = streamTutorChat(
      token,
      sessionConfig,
      currentSubject,
      apiHistory,
      fullMsg,
      abortRef.current.signal,
      drawingToSend,
      timeOfDay,
    )
    await consumeTurnStream(stream)
  }, [
    input, pendingDrawing, isStreaming, token, sessionConfig, currentSubject, subjectStart, displayMessages,
    timeOfDay, addUserMessage, stopSpeech, stopListening, consumeTurnStream,
  ])

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  const toggleMic = () => {
    if (voiceMode) {
      setVoiceMode(false)
      stopListening()
    } else {
      setVoiceMode(true)
      startListening()
    }
  }

  // Voice mode's hands-free loop: once a turn is fully over — the stream
  // has finished AND (if TTS is going to speak the reply) Bede's own voice
  // has stopped playing — restart listening automatically. Keyed off BOTH
  // isStreaming and isSpeaking transitioning together rather than either
  // alone, since whether TTS actually queues audio for a given turn (empty
  // response, TTS off/unsupported, or the backend having nothing configured)
  // isn't known in advance — this way the mic never has to guess, and never
  // restarts while Bede's own voice is still playing (which would otherwise
  // let the mic pick up Bede's reply as if the child said it).
  useEffect(() => {
    const turnActiveNow = isStreaming || isSpeaking
    if (turnActiveNow) {
      turnActiveRef.current = true
      // A new turn starting (the child responded, or Bede is already
      // mid-reply) means the previous silence is over — the timer armed
      // below no longer applies.
      clearInactivityTimer()
      return
    }
    if (turnActiveRef.current) {
      turnActiveRef.current = false
      if (voiceModeRef.current && !breakActive && !isListening) {
        startListening()
      }
      // Subject transitions used to fire on a flat 2.5s timeout regardless of
      // how long Bede's spoken transition line actually took — long lines got
      // cut off mid-sentence, short ones (or TTS off) left a dead pause. Now
      // that we know the turn (streaming + any speech) has truly finished,
      // switch after one short settling beat instead of guessing.
      if (advanceSubjectRef.current) {
        advanceSubjectRef.current = false
        setTimeout(() => nextSubject(), 1200)
        return  // sendOpener is about to fire for the new subject — no need to arm a silence timer
      }
      // The child has gone quiet after Bede's turn — give them a full
      // minute to think, type, speak, or draw before Bede gently picks the
      // thread back up (see sendContinue), rather than either resuming the
      // instant the mic happens to time out or sitting silent forever.
      if (!breakActive) {
        clearInactivityTimer()
        inactivityTimerRef.current = setTimeout(() => {
          sendContinue()
        }, INACTIVITY_TIMEOUT_MS)
      }
    }
  }, [isStreaming, isSpeaking, breakActive, isListening, startListening, nextSubject, clearInactivityTimer, sendContinue])

  // Clear any pending silence timer on unmount so a stray [CONTINUE] never
  // fires into a session the child has already left.
  useEffect(() => clearInactivityTimer, [clearInactivityTimer])

  // Dictation-mode keepalive: while voice mode is on, the mic should be LIVE
  // whenever Bede isn't thinking (streaming) or talking (speaking), we're not
  // on a break, the canvas isn't open, and no transcription is in flight —
  // no matter HOW the mic went quiet (an utterance finished, silence timed
  // out, the fallback transcribed to nothing). The transition effect above
  // restarts it at turn boundaries; this invariant catches every other way
  // it can die, so the learner converses freely without re-tapping the mic.
  // Tapping the mic off (voiceMode false) remains the only way out. The
  // short delay debounces recognition-engine restart cycles.
  useEffect(() => {
    if (!voiceMode || breakActive || showCanvas || isStreaming || isSpeaking || isListening || isTranscribing) return
    const id = setTimeout(() => startListening(), 400)
    return () => clearTimeout(id)
  }, [voiceMode, breakActive, showCanvas, isStreaming, isSpeaking, isListening, isTranscribing, startListening])

  // And the inverse guard: the moment a turn starts (Bede thinking or
  // speaking), the mic must be OFF — otherwise a [CONTINUE]-initiated turn
  // could leave a kept-alive mic hot while Bede talks, and it would hear
  // Bede's own voice as the child's answer.
  useEffect(() => {
    if ((isStreaming || isSpeaking) && isListening) stopListening()
  }, [isStreaming, isSpeaking, isListening, stopListening])

  // A break can end mid-"turn-just-ended" window (the effect above skips
  // restarting while breakActive is true and doesn't get a second chance
  // once turnActiveRef has already been cleared) — resume voice mode's
  // loop, and re-arm the silence timer, separately once the break itself
  // ends, so neither gets silently stuck off until the child notices.
  const prevBreakActiveRef = useRef(breakActive)
  useEffect(() => {
    const breakJustEnded = prevBreakActiveRef.current && !breakActive
    prevBreakActiveRef.current = breakActive
    if (breakJustEnded && !isStreaming && !isSpeaking) {
      if (voiceModeRef.current && !isListening) startListening()
      clearInactivityTimer()
      inactivityTimerRef.current = setTimeout(() => {
        sendContinue()
      }, INACTIVITY_TIMEOUT_MS)
    }
  }, [breakActive, isStreaming, isSpeaking, isListening, startListening, clearInactivityTimer, sendContinue])

  // Lets a child bring narration written offline with a smart pen/notebook
  // (e.g. inq — its own AI already transcribed the handwriting to a
  // .txt/.pdf) straight into the chat input, same as anything typed or
  // spoken — reads the file client-side, sends it to the backend for text
  // extraction only (nothing is stored), then drops the result into the
  // input box so the child can review or edit it before sending normally.
  const handleNarrationFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''  // allow re-selecting the same file next time
    if (!file || !token) return
    setUploadingNarration(true)
    try {
      const dataUrl = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(reader.result as string)
        reader.onerror = () => reject(new Error('Could not read that file'))
        reader.readAsDataURL(file)
      })
      const text = await extractNarrationText(token, file.name, dataUrl.slice(dataUrl.indexOf(',') + 1))
      setInput((prev) => (prev.trim() ? prev + '\n' + text : text))
    } catch (err) {
      addToolMessage('error', `⚠️ ${err instanceof Error ? err.message : 'Could not read that file'}`)
    } finally {
      setUploadingNarration(false)
    }
  }

  const fontClass = gradeStage === 'K-2' ? 'text-lg' : 'text-base'

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div className={`flex-1 overflow-y-auto px-4 py-4 space-y-3 ${fontClass}`}>
        {displayMessages.map((msg) => (
          <MessageBubble key={msg.id} msg={msg} studentName={sessionConfig?.student_name ?? 'You'} bubbleClass={bubble.className} />
        ))}
        {isStreaming &&
          displayMessages.find((m) => m.id === 'streaming-response')?.content === '' && (
            <div className="flex items-center gap-2 text-sage-700 text-sm animate-pulse-soft">
              <Loader2 size={14} className="animate-spin" />
              <span>Bede is thinking…</span>
            </div>
          )}
        {/* Interim speech-to-text preview */}
        {isListening && interim && (
          <div className="flex justify-end">
            <div className="max-w-[80%] rounded-2xl px-4 py-3 text-sm bg-sage-200/60 text-sage-800 italic border border-sage-200 animate-pulse-soft">
              {interim}…
            </div>
          </div>
        )}
        {isTranscribing && (
          <div className="flex justify-end">
            <div className="max-w-[80%] rounded-2xl px-4 py-3 text-sm bg-sage-200/60 text-sage-800 italic border border-sage-200 animate-pulse-soft flex items-center gap-2">
              <Loader2 size={12} className="animate-spin" /> Transcribing…
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Drawing preview */}
      {pendingDrawing && (
        <div className="px-4 pb-2 flex items-center gap-2 bg-parchment-50 border-t border-sage-200 pt-2">
          <img src={pendingDrawing} alt="Your drawing" className="h-16 w-auto rounded-lg border border-sage-200 shadow-sm" />
          <div className="flex-1 text-xs text-sage-800">Drawing ready. Add a note, or just send it.</div>
          <button onClick={() => setPendingDrawing(null)} className="text-gray-400 hover:text-gray-600">
            <X size={14} />
          </button>
        </div>
      )}

      {/* Input bar */}
      <div className="px-4 py-3 bg-parchment-50 border-t border-sage-200">
        <div className="flex gap-2 items-end">
          {/* Pen/drawing button */}
          <button
            onClick={() => setShowCanvas(true)}
            disabled={isStreaming || breakActive}
            title="Draw or write by hand"
            className="p-2.5 rounded-lg bg-sage-100 text-sage-700 hover:bg-sage-200 disabled:opacity-40 transition-all hover:scale-110 active:scale-95 flex-shrink-0"
          >
            <PenLine size={18} />
          </button>

          {/* Upload narration from a smart pen/notebook (e.g. inq) */}
          <input
            ref={narrationFileInputRef}
            type="file"
            accept=".txt,.pdf"
            onChange={handleNarrationFile}
            className="hidden"
          />
          <button
            onClick={() => narrationFileInputRef.current?.click()}
            disabled={isStreaming || breakActive || uploadingNarration}
            title="Upload narration from your notebook (e.g. inq)"
            className="p-2.5 rounded-lg bg-sage-100 text-sage-700 hover:bg-sage-200 disabled:opacity-40 transition-all hover:scale-110 active:scale-95 flex-shrink-0"
          >
            {uploadingNarration ? <Loader2 size={18} className="animate-spin" /> : <FileUp size={18} />}
          </button>

          {/* Bede's avatar — a quiet "he's talking" tell, not just the Volume2
              icon's pulse: a small bounce + glow while his voice is actually
              playing, still the moment it stops. Same isSpeaking state the
              Volume2 icon below already uses, so this never drifts out of
              sync with what's actually true. */}
          <img
            src="/bede-icon.webp"
            alt="Bede"
            className={`w-9 h-9 rounded-full object-cover shrink-0 transition-transform duration-150 ${
              isSpeaking ? 'animate-bede-talk ring-2 ring-amber-300 shadow-[0_0_10px_rgba(217,180,90,0.6)]' : ''
            }`}
          />

          {/* TTS toggle */}
          {ttsSupported && (
            <button
              onClick={toggleTTS}
              title={ttsEnabled ? 'Mute Bede' : 'Unmute Bede'}
              className={`p-2.5 rounded-lg transition-all hover:scale-110 active:scale-95 flex-shrink-0 ${
                ttsEnabled
                  ? 'bg-sage-100 text-sage-700 hover:bg-sage-200'
                  : 'bg-gray-100 text-gray-400 hover:text-gray-600'
              }`}
            >
              {ttsEnabled ? (
                isSpeaking ? <Volume2 size={18} className="animate-pulse" /> : <Volume2 size={18} />
              ) : (
                <VolumeX size={18} />
              )}
            </button>
          )}

          {/* Mic button — toggles voice mode on/off; disabled only when
              trying to TURN ON during a busy state, never when turning off */}
          {sttSupported && (
            <button
              onClick={toggleMic}
              disabled={!voiceMode && (isStreaming || breakActive || isTranscribing)}
              title={
                voiceMode
                  ? 'Voice mode on. Tap to turn off.'
                  : isTranscribing
                  ? 'Transcribing…'
                  : 'Turn on voice mode'
              }
              className={`p-2.5 rounded-lg transition-all hover:scale-110 active:scale-95 flex-shrink-0 ${
                voiceMode
                  ? isListening
                    ? 'bg-red-500 text-white animate-pulse'
                    : 'bg-red-500 text-white'
                  : 'bg-sage-100 text-sage-700 hover:bg-sage-200 disabled:opacity-40'
              }`}
            >
              {isTranscribing ? <Loader2 size={18} className="animate-spin" /> : voiceMode ? <MicOff size={18} /> : <Mic size={18} />}
            </button>
          )}

          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKey}
            disabled={isStreaming || breakActive}
            placeholder={
              breakActive
                ? 'On a break. Bede will be here when you return.'
                : isListening
                ? 'Listening… speak now'
                : voiceMode
                ? 'Voice mode on. Waiting for Bede…'
                : sttSupported
                ? 'Type or tap the mic to speak…'
                : 'Share your thoughts or answer Bede\'s question…'
            }
            rows={2}
            className="flex-1 resize-none rounded-lg border border-sage-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sage-400 bg-white placeholder-gray-400 disabled:bg-gray-50"
          />

          <button
            onClick={() => send()}
            disabled={isStreaming || breakActive || (!input.trim() && !pendingDrawing)}
            className="p-2.5 rounded-lg bg-sage-500 text-white hover:bg-sage-600 disabled:opacity-40 disabled:cursor-not-allowed transition-all hover:scale-110 active:scale-95 disabled:hover:scale-100 flex-shrink-0"
          >
            {isStreaming ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
          </button>
        </div>
        <p className="text-xs text-gray-400 mt-1.5">
          {voiceMode
            ? 'Voice mode on. Just speak, and Bede will hear and reply automatically. Tap the mic to turn it off.'
            : sttSupported
            ? 'Enter to send · mic for voice input'
            : 'Press Enter to send · Shift+Enter for new line'}
        </p>
      </div>

      {/* Handwriting overlay */}
      {showCanvas && (
        <HandwritingCanvas onSubmit={handleDrawingSubmit} onCancel={handleDrawingCancel} subject={currentSubject} gradeStage={gradeStage} />
      )}
    </div>
  )
}

interface MsgProps {
  msg: {
    id: string
    role: 'user' | 'assistant' | 'system'
    content: string
    tool?: string
    visualAid?: import('../types').VisualAidData
    timestamp: Date
  }
  studentName: string
  // The reader's chosen bubble color (useChatTheme) — passed down from the
  // one hook instance at the top of SocraticChat rather than re-subscribing
  // in every bubble.
  bubbleClass: string
}

function MessageBubble({ msg, studentName, bubbleClass }: MsgProps) {
  if (msg.role === 'system') {
    return (
      <div className="flex justify-center">
        <div className="text-xs text-gray-400 bg-white border border-gray-100 rounded-full px-3 py-1 italic">
          {msg.content}
        </div>
      </div>
    )
  }

  if (msg.visualAid) {
    return <VisualAidCard aid={msg.visualAid} />
  }

  if (msg.tool) {
    const isCelebration = msg.tool === 'celebrate_discovery'
    const toolAccent: Record<string, string> = {
      request_narration:   'border-l-[3px] border-amber-400 bg-amber-50/70',
      invite_handwriting:  'border-l-[3px] border-purple-400 bg-purple-50/70',
      offer_socratic_hint: 'border-l-[3px] border-navy-300 bg-navy-50/70',
      celebrate_discovery: 'border-l-[3px] border-emerald-400 bg-gradient-to-r from-emerald-50 to-emerald-50/40 shadow-sm shadow-emerald-100',
      connect_to_faith:    'border-l-[3px] border-gold-400 bg-gold-50/70',
      subject_complete:    'border-l-[3px] border-navy-400 bg-navy-50/70 font-medium',
    }
    const cls = toolAccent[msg.tool] ?? 'border-l-[3px] border-gray-300 bg-gray-50/70'
    return (
      <div className={`pl-3 pr-4 py-2.5 rounded-r-xl text-sm leading-relaxed text-gray-700 ${isCelebration ? 'animate-celebrate' : 'animate-slide-up'} ${cls}`}>
        {isCelebration && <Sparkles size={14} className="inline-block mr-1.5 mb-0.5 text-emerald-500" />}
        {renderEmphasis(msg.content)}
      </div>
    )
  }

  const isUser = msg.role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} animate-fade-in`}>
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
          isUser
            ? `${bubbleClass} text-white rounded-br-sm`
            : 'bg-parchment-50 border border-sage-200 text-gray-800 rounded-bl-sm shadow-sm'
        }`}
      >
        {!isUser && <div className="text-xs font-semibold text-sage-700 mb-1">Bede</div>}
        {/* white/85 (not a sage tint) so the name stays legible on every
            bubble color, not only the green default */}
        {isUser && <div className="text-xs font-semibold text-white/85 mb-1">{studentName}</div>}
        <div className="whitespace-pre-wrap">{renderEmphasis(msg.content)}</div>
      </div>
    </div>
  )
}
