import { useState, useRef, useCallback, useEffect } from 'react'
import { Send, Loader2, Mic, MicOff, Volume2, VolumeX, PenLine, X, ShieldAlert, Lock, Sparkles, Clock } from 'lucide-react'
import {
  streamTutorChat, login, getDemoConfig, decodeExpiry, SUBJECTS, SUBJECT_LABELS,
  type Subject, type SessionConfig, type ChatMessage, type VisualAidData,
} from './api'
import { useSpeechRecognition } from './useSpeechRecognition'
import { useTextToSpeech } from './useTextToSpeech'
import HandwritingCanvas from './HandwritingCanvas'
import VisualAidCard from './VisualAidCard'

// Session token only — sessionStorage so a reload within the same tab
// doesn't force re-entering the PIN, but it's gone the moment the tab
// closes. The server enforces the real 15-minute expiry regardless of
// anything kept client-side; this is just for the countdown UI.
const AUTH_KEY = 'bede_demo_auth'

interface DisplayMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  tool?: string
  visualAid?: VisualAidData
}

function loadAuth(): { token: string; expiresAt: number | null } | null {
  try {
    const raw = sessionStorage.getItem(AUTH_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed.expiresAt || parsed.expiresAt <= Date.now()) return null
    return parsed
  } catch {
    return null
  }
}

function PinLoginScreen({ onLoggedIn }: { onLoggedIn: (token: string, expiresAt: number | null) => void }) {
  const [pin, setPin] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      const { token, expiresAt } = await login(pin.trim())
      sessionStorage.setItem(AUTH_KEY, JSON.stringify({ token, expiresAt }))
      onLoggedIn(token, expiresAt)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not log in')
      setPin('')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-parchment-100 via-navy-50 to-gold-100 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-lg border border-navy-100 w-full max-w-sm p-8">
        <div className="text-center mb-6">
          <img src={`${import.meta.env.BASE_URL}bede-portrait.jpg`} alt="Bede" className="w-32 h-32 mx-auto mb-3 rounded-full object-cover object-top drop-shadow-md" />
          <h1 className="text-2xl font-display font-bold text-gray-800">Bede — Demo</h1>
          <p className="text-sm text-gray-500 mt-1">Your Classical Homeschool Tutor</p>
        </div>

        <div className="flex items-start gap-2.5 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2.5 mb-5 text-xs text-amber-800">
          <ShieldAlert size={16} className="flex-shrink-0 mt-0.5" />
          <p>
            <strong>Shared public demo.</strong> One session, 15 minutes, then you're logged
            out automatically. Nothing you type here is saved after that.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="label">Demo PIN</label>
            <input
              type="password" inputMode="numeric" autoFocus
              className="input text-center text-lg tracking-widest"
              value={pin} onChange={(e) => setPin(e.target.value)}
              placeholder="••••••"
            />
          </div>
          {error && <p className="text-sm text-red-600 text-center">{error}</p>}
          <button
            type="submit" disabled={!pin.trim() || loading}
            className="w-full py-3 bg-navy-500 text-white rounded-lg font-medium hover:bg-navy-600 disabled:opacity-40 transition-colors flex items-center justify-center gap-2"
          >
            {loading ? <Loader2 size={18} className="animate-spin" /> : 'Start the demo'}
          </button>
        </form>
      </div>
    </div>
  )
}

function ChatScreen({ token, config, onLoggedOut }: { token: string; config: SessionConfig; onLoggedOut: () => void }) {
  const [subject, setSubject] = useState<Subject>(config.subjects[0] ?? 'living_books')
  const [messages, setMessages] = useState<DisplayMessage[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [showCanvas, setShowCanvas] = useState(false)
  const [pendingDrawing, setPendingDrawing] = useState<string | null>(null)
  const [ttsEnabled, setTtsEnabled] = useState(true)
  const [remainingSecs, setRemainingSecs] = useState<number | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const openerFired = useRef(new Set<Subject>())

  const { speak, stop: stopSpeech, isSpeaking } = useTextToSpeech(null, null)
  const { isListening, interim, isSupported: sttSupported, start: startListening, stop: stopListening } =
    useSpeechRecognition((transcript) => setInput((prev) => (prev ? prev + ' ' + transcript : transcript)))

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  // 15-minute countdown, ticking from the token's real exp claim — auto-logout at zero.
  useEffect(() => {
    const tick = () => {
      const auth = loadAuth()
      if (!auth || !auth.expiresAt) { onLoggedOut(); return }
      const secs = Math.max(0, Math.round((auth.expiresAt - Date.now()) / 1000))
      setRemainingSecs(secs)
      if (secs <= 0) onLoggedOut()
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const historyForApi = useCallback((): ChatMessage[] => {
    return messages
      .filter((m) => m.role !== 'system' && !m.tool && !m.visualAid)
      .map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content }))
  }, [messages])

  const runStream = useCallback(async (childMessage: string, drawingImage: string | null) => {
    setIsStreaming(true)
    abortRef.current?.abort()
    abortRef.current = new AbortController()
    const assistantId = `assistant-${Date.now()}`
    setMessages((prev) => [...prev, { id: assistantId, role: 'assistant', content: '' }])
    let fullText = ''
    try {
      for await (const chunk of streamTutorChat(token, config, subject, historyForApi(), childMessage, drawingImage, abortRef.current.signal)) {
        if (chunk.type === 'text') {
          fullText += chunk.content
          setMessages((prev) => prev.map((m) => (m.id === assistantId ? { ...m, content: fullText } : m)))
        } else if (chunk.type === 'tool') {
          setMessages((prev) => [...prev, { id: `tool-${Date.now()}-${Math.random()}`, role: 'assistant', content: chunk.content, tool: chunk.tool }])
          if (ttsEnabled) speak(chunk.content)
        } else if (chunk.type === 'visual_aid') {
          setMessages((prev) => [...prev, { id: `aid-${Date.now()}-${Math.random()}`, role: 'assistant', content: '', visualAid: chunk.visualAid }])
        } else if (chunk.type === 'done') {
          break
        }
      }
      if (ttsEnabled && fullText) speak(fullText)
    } catch (err) {
      setMessages((prev) => prev.filter((m) => m.id !== assistantId || m.content))
      if (err instanceof Error && err.name !== 'AbortError') {
        setMessages((prev) => [...prev, { id: `err-${Date.now()}`, role: 'system', content: `⚠️ ${err.message}` }])
        if (err.message.includes('session has ended')) onLoggedOut()
      }
    } finally {
      setIsStreaming(false)
    }
  }, [token, config, subject, historyForApi, ttsEnabled, speak, onLoggedOut])

  // Fire Bede's opener once per subject
  useEffect(() => {
    if (openerFired.current.has(subject)) return
    openerFired.current.add(subject)
    runStream('[START]', null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [subject])

  const send = () => {
    const msg = input.trim()
    if ((!msg && !pendingDrawing) || isStreaming) return
    stopSpeech()
    stopListening()
    setInput('')
    const fullMsg = pendingDrawing ? msg + (msg ? ' ' : '') + '[✏️ Drawing]' : msg
    const drawing = pendingDrawing
    setPendingDrawing(null)
    setMessages((prev) => [...prev, { id: `user-${Date.now()}`, role: 'user', content: fullMsg }])
    runStream(fullMsg, drawing ? drawing.slice(drawing.indexOf(',') + 1) : null)
  }

  const toggleMic = () => (isListening ? stopListening() : startListening())

  const logout = () => {
    sessionStorage.removeItem(AUTH_KEY)
    abortRef.current?.abort()
    onLoggedOut()
  }

  const lowTime = remainingSecs !== null && remainingSecs <= 60

  return (
    <div className="flex flex-col h-screen bg-gradient-to-br from-parchment-50 via-parchment-50 to-navy-50/40">
      <header className="bg-white border-b border-navy-100 shrink-0 h-14 flex items-center px-4 gap-3">
        <img src={`${import.meta.env.BASE_URL}bede-icon.png`} alt="Bede" className="w-8 h-8 rounded-full object-cover" />
        <div className="flex-1 min-w-0">
          <span className="text-navy-700 font-semibold text-sm">Bede</span>
          <span className="text-gray-400 text-xs ml-2">with {config.student_name}</span>
        </div>
        {remainingSecs !== null && (
          <div className={`flex items-center gap-1 text-xs font-mono tabular-nums ${lowTime ? 'text-red-500' : 'text-gray-400'}`}>
            <Clock size={12} />
            {String(Math.floor(remainingSecs / 60)).padStart(1, '0')}:{String(remainingSecs % 60).padStart(2, '0')}
          </div>
        )}
        <select
          value={subject}
          onChange={(e) => setSubject(e.target.value as Subject)}
          className="text-xs border border-navy-200 rounded-lg px-2 py-1.5 bg-white"
        >
          {config.subjects.map((s) => <option key={s} value={s}>{SUBJECT_LABELS[s]}</option>)}
        </select>
        <button onClick={logout} className="text-xs text-gray-400 hover:text-gray-600 underline">Log out</button>
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
        {messages.map((msg) => (
          <MessageBubble key={msg.id} msg={msg} studentName={config.student_name} />
        ))}
        {isStreaming && messages.at(-1)?.content === '' && !messages.at(-1)?.visualAid && (
          <div className="flex items-center gap-2 text-navy-500 text-sm">
            <Loader2 size={14} className="animate-spin" /> <span>Bede is thinking…</span>
          </div>
        )}
        {isListening && interim && (
          <div className="flex justify-end">
            <div className="max-w-[80%] rounded-2xl px-4 py-3 text-sm bg-navy-200/60 text-navy-800 italic border border-navy-200">{interim}…</div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {pendingDrawing && (
        <div className="px-4 pb-2 flex items-center gap-2 bg-white border-t border-parchment-200 pt-2">
          <img src={pendingDrawing} alt="Your drawing" className="h-16 w-auto rounded-lg border border-navy-200 shadow-sm" />
          <div className="flex-1 text-xs text-navy-700">Drawing ready — add a note or send</div>
          <button onClick={() => setPendingDrawing(null)} className="text-gray-400 hover:text-gray-600"><X size={14} /></button>
        </div>
      )}

      <div className="px-4 py-3 bg-white border-t border-parchment-200">
        <div className="flex gap-2 items-end">
          <button onClick={() => setShowCanvas(true)} disabled={isStreaming} className="p-2.5 rounded-lg bg-navy-100 text-navy-600 hover:bg-navy-200 disabled:opacity-40 transition-all hover:scale-110 active:scale-95 flex-shrink-0">
            <PenLine size={18} />
          </button>
          <button onClick={() => (ttsEnabled ? (setTtsEnabled(false), stopSpeech()) : setTtsEnabled(true))} className={`p-2.5 rounded-lg transition-all hover:scale-110 active:scale-95 flex-shrink-0 ${ttsEnabled ? 'bg-navy-100 text-navy-600' : 'bg-gray-100 text-gray-400'}`}>
            {ttsEnabled ? (isSpeaking ? <Volume2 size={18} className="animate-pulse" /> : <Volume2 size={18} />) : <VolumeX size={18} />}
          </button>
          {sttSupported && (
            <button onClick={toggleMic} disabled={isStreaming} className={`p-2.5 rounded-lg transition-all hover:scale-110 active:scale-95 flex-shrink-0 ${isListening ? 'bg-red-500 text-white animate-pulse' : 'bg-navy-100 text-navy-600 hover:bg-navy-200 disabled:opacity-40'}`}>
              {isListening ? <MicOff size={18} /> : <Mic size={18} />}
            </button>
          )}
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
            disabled={isStreaming}
            placeholder={isListening ? 'Listening… speak now' : 'Type or tap the mic to speak…'}
            rows={2}
            className="flex-1 resize-none rounded-lg border border-navy-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-navy-400 bg-white"
          />
          <button onClick={send} disabled={isStreaming || (!input.trim() && !pendingDrawing)} className="p-2.5 rounded-lg bg-navy-500 text-white hover:bg-navy-600 disabled:opacity-40 transition-all hover:scale-110 active:scale-95 disabled:hover:scale-100 flex-shrink-0">
            {isStreaming ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
          </button>
        </div>
      </div>

      {showCanvas && (
        <HandwritingCanvas
          onSubmit={(dataUrl) => { setPendingDrawing(dataUrl); setShowCanvas(false) }}
          onCancel={() => setShowCanvas(false)}
        />
      )}
    </div>
  )
}

function MessageBubble({ msg, studentName }: { msg: DisplayMessage; studentName: string }) {
  if (msg.role === 'system') {
    return <div className="flex justify-center"><div className="text-xs text-gray-400 bg-white border border-gray-100 rounded-full px-3 py-1 italic">{msg.content}</div></div>
  }
  if (msg.visualAid) {
    return <VisualAidCard aid={msg.visualAid} />
  }
  if (msg.tool) {
    const isCelebration = msg.tool === 'celebrate_discovery'
    const accent: Record<string, string> = {
      request_narration: 'border-l-[3px] border-amber-400 bg-amber-50/70',
      offer_socratic_hint: 'border-l-[3px] border-navy-300 bg-navy-50/70',
      celebrate_discovery: 'border-l-[3px] border-emerald-400 bg-gradient-to-r from-emerald-50 to-emerald-50/40 shadow-sm shadow-emerald-100',
      connect_to_faith: 'border-l-[3px] border-gold-400 bg-gold-50/70',
    }
    return (
      <div className={`pl-3 pr-4 py-2.5 rounded-r-xl text-sm leading-relaxed text-gray-700 ${isCelebration ? 'animate-celebrate' : 'animate-slide-up'} ${accent[msg.tool] ?? 'border-l-[3px] border-gray-300 bg-gray-50/70'}`}>
        {isCelebration && <Sparkles size={14} className="inline-block mr-1.5 mb-0.5 text-emerald-500" />}
        {msg.content}
      </div>
    )
  }
  const isUser = msg.role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} animate-fade-in`}>
      <div className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${isUser ? 'bg-navy-500 text-white rounded-br-sm' : 'bg-white border border-navy-100 text-gray-800 rounded-bl-sm shadow-sm'}`}>
        {!isUser && <div className="text-xs font-semibold text-navy-600 mb-1">Bede</div>}
        {isUser && <div className="text-xs font-semibold text-navy-100 mb-1">{studentName}</div>}
        <div className="whitespace-pre-wrap">{msg.content}</div>
      </div>
    </div>
  )
}

export default function App() {
  const [auth, setAuth] = useState<{ token: string; expiresAt: number | null } | null>(() => loadAuth())
  const [config, setConfig] = useState<SessionConfig | null>(null)
  const [configError, setConfigError] = useState('')

  useEffect(() => {
    if (!auth) { setConfig(null); return }
    getDemoConfig(auth.token)
      .then(setConfig)
      .catch((err) => setConfigError(err instanceof Error ? err.message : 'Could not load demo session'))
  }, [auth])

  const handleLoggedOut = () => {
    sessionStorage.removeItem(AUTH_KEY)
    setAuth(null)
    setConfig(null)
    setConfigError('')
  }

  if (!auth) {
    return <PinLoginScreen onLoggedIn={(token, expiresAt) => setAuth({ token, expiresAt })} />
  }

  if (configError) {
    return (
      <div className="min-h-screen bg-parchment-50 flex flex-col items-center justify-center gap-4 p-8 text-center">
        <Lock size={32} className="text-gray-400" />
        <p className="text-gray-700 font-medium">Could not start the demo</p>
        <p className="text-sm text-gray-500 max-w-sm">{configError}</p>
        <button onClick={handleLoggedOut} className="mt-2 text-sm text-navy-600 underline">Back to login</button>
      </div>
    )
  }

  if (!config) {
    return (
      <div className="min-h-screen bg-parchment-50 flex flex-col items-center justify-center gap-4">
        <Loader2 size={28} className="text-navy-500 animate-spin" />
        <p className="text-sm text-gray-500">Loading your session…</p>
      </div>
    )
  }

  return <ChatScreen token={auth.token} config={config} onLoggedOut={handleLoggedOut} />
}
