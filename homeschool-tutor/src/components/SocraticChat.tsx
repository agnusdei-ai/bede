import { useState, useRef, useEffect, useCallback } from 'react'
import { Send, Loader2, Mic, MicOff, Volume2, VolumeX, PenLine, X, Sparkles } from 'lucide-react'
import { streamTutorChat } from '../services/api'
import { getApiMessages, useSessionStore } from '../store/sessionStore'
import { useHybridVoiceInput } from '../hooks/useHybridVoiceInput'
import { useTextToSpeech } from '../hooks/useTextToSpeech'
import HandwritingCanvas from './HandwritingCanvas'
import VisualAidCard from './VisualAidCard'

export default function SocraticChat({ breakActive = false, gradeStage }: { breakActive?: boolean; gradeStage?: string }) {
  const [input, setInput] = useState('')
  const [showCanvas, setShowCanvas] = useState(false)
  const [pendingDrawing, setPendingDrawing] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const lastAssistantRef = useRef('')  // track last spoken text to avoid re-speaking
  const advanceSubjectRef = useRef(false)  // set when Bede signals mastery/frustration mid-stream

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
  } = useSessionStore()

  // ── Text-to-speech: Bede speaks its responses ────────────────────────────
  const { speak, stop: stopSpeech, toggle: toggleTTS, isSpeaking, enabled: ttsEnabled, isSupported: ttsSupported } = useTextToSpeech(token)

  // ── Speech recognition: child speaks instead of typing ──────────────────
  // Native Web Speech API first, auto-falls back to recording + server-side
  // Whisper transcription when it's unsupported, errors, or silently stalls
  // (Safari/iOS are known to do this — see useHybridVoiceInput).
  const { isListening, isTranscribing, interim, isSupported: sttSupported, start: startListening, stop: stopListening } = useHybridVoiceInput({
    token,
    onFinal: (transcript) => {
      setInput((prev) => (prev ? prev + ' ' + transcript : transcript))
    },
  })

  // Track which subjects have already received their opening message
  const openerFiredRef = useRef(new Set<string>())

  // sendOpener reads live store state to avoid stale-closure issues during streaming
  const sendOpener = useCallback(async () => {
    const state = useSessionStore.getState()
    if (state.isStreaming || !state.token || !state.sessionConfig) return

    state.startAssistantStream()
    abortRef.current?.abort()
    abortRef.current = new AbortController()

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
        } else if (chunk.type === 'tool' && chunk.content) {
          addToolMessage(chunk.tool ?? 'tool', chunk.content)
          speak(chunk.content)
        } else if (chunk.type === 'assessment') {
          // Silent server-side narration score — no UI change for child
        } else if (chunk.type === 'visual_aid' && chunk.visualAid) {
          addVisualAidMessage(chunk.visualAid)
        } else if (chunk.type === 'subject_complete') {
          addToolMessage('subject_complete', chunk.content ?? "Let's move on to our next subject!")
          speak(chunk.content ?? '')
          advanceSubjectRef.current = true
        } else if (chunk.type === 'done') {
          break
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name !== 'AbortError') {
        addToolMessage('error', `⚠️ ${err.message}`)
      }
    } finally {
      finalizeAssistantMessage()
      setStreaming(false)
      if (advanceSubjectRef.current) {
        advanceSubjectRef.current = false
        // Brief pause so the child can read Bede's transition line before the
        // subject switches and the next opener fires.
        setTimeout(() => nextSubject(), 2500)
      }
    }
  }, [appendAssistantChunk, addToolMessage, addVisualAidMessage, finalizeAssistantMessage, setStreaming, speak, nextSubject])

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

  // Auto-speak new assistant messages
  useEffect(() => {
    const lastAssistant = displayMessages
      .filter((m) => m.role === 'assistant' && m.id !== 'streaming-response' && !m.tool)
      .at(-1)

    if (lastAssistant && lastAssistant.content && lastAssistant.content !== lastAssistantRef.current) {
      lastAssistantRef.current = lastAssistant.content
      speak(lastAssistant.content)
    }
  }, [displayMessages, speak])

  const handleDrawingSubmit = (imageDataUrl: string) => {
    setPendingDrawing(imageDataUrl)
    setShowCanvas(false)
  }
  const handleDrawingCancel = () => setShowCanvas(false)

  const send = useCallback(async () => {
    const msg = input.trim()
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
        } else if (chunk.type === 'tool' && chunk.content) {
          addToolMessage(chunk.tool ?? 'tool', chunk.content)
          // Speak tool responses too (narration prompts, hints, etc.)
          speak(chunk.content)
        } else if (chunk.type === 'assessment') {
          // Silent server-side narration score — no UI change for child
        } else if (chunk.type === 'visual_aid' && chunk.visualAid) {
          addVisualAidMessage(chunk.visualAid)
        } else if (chunk.type === 'subject_complete') {
          addToolMessage('subject_complete', chunk.content ?? "Let's move on to our next subject!")
          speak(chunk.content ?? '')
          advanceSubjectRef.current = true
        } else if (chunk.type === 'done') {
          break
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name !== 'AbortError') {
        addToolMessage('error', `⚠️ ${err.message}`)
      }
    } finally {
      finalizeAssistantMessage()
      setStreaming(false)
      if (advanceSubjectRef.current) {
        advanceSubjectRef.current = false
        setTimeout(() => nextSubject(), 2500)
      }
    }
  }, [
    input, pendingDrawing, isStreaming, token, sessionConfig, currentSubject, subjectStart, displayMessages,
    addUserMessage, appendAssistantChunk, addToolMessage, addVisualAidMessage, finalizeAssistantMessage,
    setStreaming, stopSpeech, stopListening, speak, nextSubject,
  ])

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  const toggleMic = () => {
    if (isListening) stopListening()
    else startListening()
  }

  const fontClass = gradeStage === 'K-2' ? 'text-base' : 'text-sm'

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

          {/* Mic button */}
          {sttSupported && (
            <button
              onClick={toggleMic}
              disabled={isStreaming || breakActive || isTranscribing}
              title={isListening ? 'Stop listening' : isTranscribing ? 'Transcribing…' : 'Speak your answer'}
              className={`p-2.5 rounded-lg transition-all hover:scale-110 active:scale-95 flex-shrink-0 ${
                isListening
                  ? 'bg-red-500 text-white animate-pulse'
                  : 'bg-navy-100 text-navy-600 hover:bg-navy-200 disabled:opacity-40'
              }`}
            >
              {isTranscribing ? <Loader2 size={18} className="animate-spin" /> : isListening ? <MicOff size={18} /> : <Mic size={18} />}
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
                : sttSupported
                ? 'Type or tap the mic to speak…'
                : 'Share your thoughts or answer Bede\'s question…'
            }
            rows={2}
            className="flex-1 resize-none rounded-lg border border-navy-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-navy-400 bg-white placeholder-gray-400 disabled:bg-gray-50"
          />

          <button
            onClick={send}
            disabled={isStreaming || breakActive || (!input.trim() && !pendingDrawing)}
            className="p-2.5 rounded-lg bg-navy-500 text-white hover:bg-navy-600 disabled:opacity-40 disabled:cursor-not-allowed transition-all hover:scale-110 active:scale-95 disabled:hover:scale-100 flex-shrink-0"
          >
            {isStreaming ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
          </button>
        </div>
        <p className="text-xs text-gray-400 mt-1.5">
          {sttSupported ? 'Enter to send · mic for voice input' : 'Press Enter to send · Shift+Enter for new line'}
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
