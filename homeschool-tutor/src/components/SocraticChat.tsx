import { useState, useRef, useEffect, useCallback } from 'react'
import { Send, Loader2, Mic, MicOff, Volume2, VolumeX, PenLine, FileUp, X, Sparkles } from 'lucide-react'
import { streamTutorChat, updateVoiceNarrationPreference, extractNarrationText } from '../services/api'
import { getApiMessages, useSessionStore } from '../store/sessionStore'
import { useHybridVoiceInput } from '../hooks/useHybridVoiceInput'
import { useTextToSpeech } from '../hooks/useTextToSpeech'
import HandwritingCanvas from './HandwritingCanvas'
import VisualAidCard from './VisualAidCard'

export default function SocraticChat({ breakActive = false, gradeStage }: { breakActive?: boolean; gradeStage?: string }) {
  const [input, setInput] = useState('')
  const [showCanvas, setShowCanvas] = useState(false)
  const [pendingDrawing, setPendingDrawing] = useState<string | null>(null)
  const [uploadingNarration, setUploadingNarration] = useState(false)
  const narrationFileInputRef = useRef<HTMLInputElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const advanceSubjectRef = useRef(false)  // set when Bede signals mastery/frustration mid-stream

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

    // Speak the whole turn as ONE synthesis call, not one call per chunk.
    // Separate independently-synthesized clips (main text, then each tool
    // card) stitched together with a network round-trip gap between them
    // read as choppy and mechanical even when each clip's own voice quality
    // is fine — a single continuous take sounds like one person talking.
    const speechSegments: string[] = []
    let pendingText = ''
    const flush = () => {
      if (pendingText.trim()) speechSegments.push(pendingText)
      pendingText = ''
    }
    try {
      const stream = streamTutorChat(
        state.token,
        state.sessionConfig,
        state.currentSubject,
        [],          // no prior history — clean slate for each subject opener
        '[START]',
        abortRef.current.signal,
      )
      for await (const chunk of stream) {
        if (chunk.type === 'text' && chunk.content) {
          appendAssistantChunk(chunk.content)
          pendingText += chunk.content
        } else if (chunk.type === 'tool' && chunk.content) {
          flush()
          addToolMessage(chunk.tool ?? 'tool', chunk.content)
          if (chunk.tool === 'invite_handwriting') setShowCanvas(true)
          speechSegments.push(chunk.content)
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
      // above once streaming AND any queued speech have both finished.
    }
  }, [appendAssistantChunk, addToolMessage, addVisualAidMessage, finalizeAssistantMessage, setStreaming, speak, stopSpeech, stopListening])

  // Fire opener once per subject — when subject changes and session is ready
  useEffect(() => {
    if (!sessionConfig || !token) return
    if (openerFiredRef.current.has(currentSubject)) return
    openerFiredRef.current.add(currentSubject)
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

    // Append drawing indicator to message if a drawing is pending
    const fullMsg = pendingDrawing ? msg + (msg ? ' ' : '') + '[✏️ Drawing]' : msg
    const drawingToSend = pendingDrawing
    setPendingDrawing(null)

    // Snapshot current-subject history BEFORE addUserMessage mutates displayMessages
    const apiHistory = getApiMessages(displayMessages, subjectStart)
    addUserMessage(fullMsg)

    abortRef.current?.abort()
    abortRef.current = new AbortController()

    // See sendOpener's comment — the whole turn is spoken as one synthesis
    // call, not one call per chunk.
    const speechSegments: string[] = []
    let pendingText = ''
    const flush = () => {
      if (pendingText.trim()) speechSegments.push(pendingText)
      pendingText = ''
    }
    try {
      const stream = streamTutorChat(
        token,
        sessionConfig,
        currentSubject,
        apiHistory,
        fullMsg,
        abortRef.current.signal,
        drawingToSend
      )

      for await (const chunk of stream) {
        if (chunk.type === 'text' && chunk.content) {
          appendAssistantChunk(chunk.content)
          pendingText += chunk.content
        } else if (chunk.type === 'tool' && chunk.content) {
          flush()
          addToolMessage(chunk.tool ?? 'tool', chunk.content)
          if (chunk.tool === 'invite_handwriting') setShowCanvas(true)
          speechSegments.push(chunk.content)
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
      // above once streaming AND any queued speech have both finished.
    }
  }, [
    input, pendingDrawing, isStreaming, token, sessionConfig, currentSubject, subjectStart, displayMessages,
    addUserMessage, appendAssistantChunk, addToolMessage, addVisualAidMessage, finalizeAssistantMessage,
    setStreaming, stopSpeech, stopListening, speak,
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
      }
    }
  }, [isStreaming, isSpeaking, breakActive, isListening, startListening, nextSubject])

  // A break can end mid-"turn-just-ended" window (the effect above skips
  // restarting while breakActive is true and doesn't get a second chance
  // once turnActiveRef has already been cleared) — resume voice mode's
  // loop separately once the break itself ends, so it doesn't get silently
  // stuck off until the child notices and taps the mic again.
  const prevBreakActiveRef = useRef(breakActive)
  useEffect(() => {
    const breakJustEnded = prevBreakActiveRef.current && !breakActive
    prevBreakActiveRef.current = breakActive
    if (breakJustEnded && voiceModeRef.current && !isStreaming && !isSpeaking && !isListening) {
      startListening()
    }
  }, [breakActive, isStreaming, isSpeaking, isListening, startListening])

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
          <MessageBubble key={msg.id} msg={msg} studentName={sessionConfig?.student_name ?? 'You'} />
        ))}
        {isStreaming &&
          displayMessages.find((m) => m.id === 'streaming-response')?.content === '' && (
            <div className="flex items-center gap-2 text-navy-500 text-sm animate-pulse-soft">
              <Loader2 size={14} className="animate-spin" />
              <span>Bede is thinking…</span>
            </div>
          )}
        {/* Interim speech-to-text preview */}
        {isListening && interim && (
          <div className="flex justify-end">
            <div className="max-w-[80%] rounded-2xl px-4 py-3 text-sm bg-navy-200/60 text-navy-800 italic border border-navy-200 animate-pulse-soft">
              {interim}…
            </div>
          </div>
        )}
        {isTranscribing && (
          <div className="flex justify-end">
            <div className="max-w-[80%] rounded-2xl px-4 py-3 text-sm bg-navy-200/60 text-navy-800 italic border border-navy-200 animate-pulse-soft flex items-center gap-2">
              <Loader2 size={12} className="animate-spin" /> Transcribing…
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Drawing preview */}
      {pendingDrawing && (
        <div className="px-4 pb-2 flex items-center gap-2 bg-white border-t border-parchment-200 pt-2">
          <img src={pendingDrawing} alt="Your drawing" className="h-16 w-auto rounded-lg border border-navy-200 shadow-sm" />
          <div className="flex-1 text-xs text-navy-700">Drawing ready — add a note or send</div>
          <button onClick={() => setPendingDrawing(null)} className="text-gray-400 hover:text-gray-600">
            <X size={14} />
          </button>
        </div>
      )}

      {/* Input bar */}
      <div className="px-4 py-3 bg-white border-t border-parchment-200">
        <div className="flex gap-2 items-end">
          {/* Pen/drawing button */}
          <button
            onClick={() => setShowCanvas(true)}
            disabled={isStreaming || breakActive}
            title="Draw or write by hand"
            className="p-2.5 rounded-lg bg-navy-100 text-navy-600 hover:bg-navy-200 disabled:opacity-40 transition-all hover:scale-110 active:scale-95 flex-shrink-0"
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
            className="p-2.5 rounded-lg bg-navy-100 text-navy-600 hover:bg-navy-200 disabled:opacity-40 transition-all hover:scale-110 active:scale-95 flex-shrink-0"
          >
            {uploadingNarration ? <Loader2 size={18} className="animate-spin" /> : <FileUp size={18} />}
          </button>

          {/* TTS toggle */}
          {ttsSupported && (
            <button
              onClick={toggleTTS}
              title={ttsEnabled ? 'Mute Bede' : 'Unmute Bede'}
              className={`p-2.5 rounded-lg transition-all hover:scale-110 active:scale-95 flex-shrink-0 ${
                ttsEnabled
                  ? 'bg-navy-100 text-navy-600 hover:bg-navy-200'
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
                  ? 'Voice mode on — tap to turn off'
                  : isTranscribing
                  ? 'Transcribing…'
                  : 'Turn on voice mode'
              }
              className={`p-2.5 rounded-lg transition-all hover:scale-110 active:scale-95 flex-shrink-0 ${
                voiceMode
                  ? isListening
                    ? 'bg-red-500 text-white animate-pulse'
                    : 'bg-red-500 text-white'
                  : 'bg-navy-100 text-navy-600 hover:bg-navy-200 disabled:opacity-40'
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
                ? 'On a break — Bede will be here when you return'
                : isListening
                ? 'Listening… speak now'
                : voiceMode
                ? 'Voice mode on — waiting for Bede…'
                : sttSupported
                ? 'Type or tap the mic to speak…'
                : 'Share your thoughts or answer Bede\'s question…'
            }
            rows={2}
            className="flex-1 resize-none rounded-lg border border-navy-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-navy-400 bg-white placeholder-gray-400 disabled:bg-gray-50"
          />

          <button
            onClick={() => send()}
            disabled={isStreaming || breakActive || (!input.trim() && !pendingDrawing)}
            className="p-2.5 rounded-lg bg-navy-500 text-white hover:bg-navy-600 disabled:opacity-40 disabled:cursor-not-allowed transition-all hover:scale-110 active:scale-95 disabled:hover:scale-100 flex-shrink-0"
          >
            {isStreaming ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
          </button>
        </div>
        <p className="text-xs text-gray-400 mt-1.5">
          {voiceMode
            ? 'Voice mode on — just speak, Bede will hear and reply automatically. Tap the mic to turn it off.'
            : sttSupported
            ? 'Enter to send · mic for voice input'
            : 'Press Enter to send · Shift+Enter for new line'}
        </p>
      </div>

      {/* Handwriting overlay */}
      {showCanvas && (
        <HandwritingCanvas onSubmit={handleDrawingSubmit} onCancel={handleDrawingCancel} />
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
}

function MessageBubble({ msg, studentName }: MsgProps) {
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
        {msg.content}
      </div>
    )
  }

  const isUser = msg.role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} animate-fade-in`}>
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
          isUser
            ? 'bg-navy-500 text-white rounded-br-sm'
            : 'bg-white border border-navy-100 text-gray-800 rounded-bl-sm shadow-sm'
        }`}
      >
        {!isUser && <div className="text-xs font-semibold text-navy-600 mb-1">Bede</div>}
        {isUser && <div className="text-xs font-semibold text-navy-100 mb-1">{studentName}</div>}
        <div className="whitespace-pre-wrap">{msg.content}</div>
      </div>
    </div>
  )
}
