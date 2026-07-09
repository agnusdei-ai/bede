import { useState, useRef, useCallback, useEffect } from 'react'
import { Send, Loader2, Mic, MicOff, Volume2, VolumeX, PenLine, X, ShieldAlert, Lock } from 'lucide-react'
import {
  streamTutorChat, SUBJECTS, SUBJECT_LABELS,
  type Subject, type StudentProfile, type ChatMessage, type GradeStage,
} from './claude'
import { useSpeechRecognition } from './useSpeechRecognition'
import { useTextToSpeech } from './useTextToSpeech'
import HandwritingCanvas from './HandwritingCanvas'

const LS_KEYS = {
  anthropicKey: 'bede_demo_anthropic_key',
  elevenLabsKey: 'bede_demo_elevenlabs_key',
  elevenLabsVoiceId: 'bede_demo_elevenlabs_voice_id',
  student: 'bede_demo_student',
  pin: 'bede_demo_pin',
}

interface DisplayMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  tool?: string
}

const MIN_PIN_LENGTH = 6

/** At least 6 digits, no repeated digit anywhere in the PIN. */
function pinStrengthError(pin: string): string | null {
  if (!/^\d+$/.test(pin)) return 'PIN must contain only digits.'
  if (pin.length < MIN_PIN_LENGTH) return `PIN must be at least ${MIN_PIN_LENGTH} digits.`
  if (new Set(pin).size !== pin.length) return 'PIN cannot repeat any digit.'
  return null
}

function SetupScreen({ onReady }: { onReady: () => void }) {
  const [anthropicKey, setAnthropicKey] = useState('')
  const [elevenLabsKey, setElevenLabsKey] = useState('')
  const [elevenLabsVoiceId, setElevenLabsVoiceId] = useState('')
  const [name, setName] = useState('')
  const [grade, setGrade] = useState('')
  const [gradeStage, setGradeStage] = useState<GradeStage>('3-5')
  const [pin, setPin] = useState('')
  const [error, setError] = useState('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!anthropicKey.trim() || !name.trim() || !grade.trim()) {
      setError('Anthropic API key, name, and grade are all required.')
      return
    }
    if (pin.trim()) {
      const pinError = pinStrengthError(pin.trim())
      if (pinError) { setError(pinError); return }
    }
    localStorage.setItem(LS_KEYS.anthropicKey, anthropicKey.trim())
    if (elevenLabsKey.trim()) localStorage.setItem(LS_KEYS.elevenLabsKey, elevenLabsKey.trim())
    if (elevenLabsVoiceId.trim()) localStorage.setItem(LS_KEYS.elevenLabsVoiceId, elevenLabsVoiceId.trim())
    localStorage.setItem(LS_KEYS.student, JSON.stringify({ name: name.trim(), grade: grade.trim(), gradeStage }))
    if (pin.trim()) localStorage.setItem(LS_KEYS.pin, pin.trim())
    else localStorage.removeItem(LS_KEYS.pin)
    onReady()
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-parchment-100 via-navy-50 to-gold-100 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-lg border border-navy-100 w-full max-w-md p-8">
        <div className="text-center mb-6">
          <img src="/bede-portrait.jpg" alt="Bede" className="w-24 h-24 mx-auto mb-3 rounded-full object-cover object-top drop-shadow-sm" />
          <h1 className="text-2xl font-display font-bold text-gray-800">Bede — Demo</h1>
          <p className="text-sm text-gray-500 mt-1">Your Classical Homeschool Tutor</p>
        </div>

        <div className="flex items-start gap-2.5 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2.5 mb-5 text-xs text-amber-800">
          <ShieldAlert size={16} className="flex-shrink-0 mt-0.5" />
          <p>
            <strong>Demo build, not the real app.</strong> Your API key is stored only in this
            browser's local storage and sent directly to Anthropic/ElevenLabs — never to any
            server of ours. Don't use a key you care about protecting on a shared device, and
            don't rely on this for anything beyond trying Bede out.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="label">Anthropic API key (required)</label>
            <input type="password" className="input" value={anthropicKey} onChange={(e) => setAnthropicKey(e.target.value)} placeholder="sk-ant-..." />
          </div>
          <div>
            <label className="label">ElevenLabs API key (optional — for a real voice)</label>
            <input type="password" className="input" value={elevenLabsKey} onChange={(e) => setElevenLabsKey(e.target.value)} placeholder="Leave blank to use your browser's voice" />
          </div>
          {elevenLabsKey.trim() && (
            <div>
              <label className="label">ElevenLabs voice ID</label>
              <input className="input" value={elevenLabsVoiceId} onChange={(e) => setElevenLabsVoiceId(e.target.value)} placeholder="Required if you set a key above" />
            </div>
          )}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Student's name</label>
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Emma" />
            </div>
            <div>
              <label className="label">Grade</label>
              <input className="input" value={grade} onChange={(e) => setGrade(e.target.value)} placeholder="K, 4, 8..." />
            </div>
          </div>
          <div>
            <label className="label">Stage</label>
            <div className="flex rounded-lg border border-navy-200 overflow-hidden">
              {(['K-2', '3-5', '6-8'] as GradeStage[]).map((s) => (
                <button
                  key={s} type="button" onClick={() => setGradeStage(s)}
                  className={`flex-1 py-2 text-sm font-medium transition-colors ${gradeStage === s ? 'bg-navy-500 text-white' : 'bg-white text-gray-600 hover:bg-navy-50'}`}
                >{s}</button>
              ))}
            </div>
          </div>
          <div>
            <label className="label">Demo PIN screen (optional)</label>
            <input className="input" value={pin} onChange={(e) => setPin(e.target.value)} placeholder="6+ digits, no repeats — leave blank to skip" inputMode="numeric" />
            <p className="text-xs text-gray-400 mt-1">
              Shows a PIN entry step before Bede, mirroring the real app's login <em>look</em> —
              this is a UI demonstration only, not real security (see the notice on that screen).
              If set: at least {MIN_PIN_LENGTH} digits, no digit repeated.
            </p>
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button type="submit" className="w-full py-3 bg-navy-500 text-white rounded-lg font-medium hover:bg-navy-600 transition-colors">
            Start the demo
          </button>
        </form>
      </div>
    </div>
  )
}

function ChatScreen({ student, onReset }: { student: StudentProfile; onReset: () => void }) {
  const anthropicKey = localStorage.getItem(LS_KEYS.anthropicKey) ?? ''
  const elevenLabsKey = localStorage.getItem(LS_KEYS.elevenLabsKey)
  const elevenLabsVoiceId = localStorage.getItem(LS_KEYS.elevenLabsVoiceId)

  const [subject, setSubject] = useState<Subject>('living_books')
  const [messages, setMessages] = useState<DisplayMessage[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [showCanvas, setShowCanvas] = useState(false)
  const [pendingDrawing, setPendingDrawing] = useState<string | null>(null)
  const [ttsEnabled, setTtsEnabled] = useState(true)
  const bottomRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const openerFired = useRef(new Set<Subject>())

  const { speak, stop: stopSpeech, isSpeaking } = useTextToSpeech(elevenLabsKey, elevenLabsVoiceId)
  const { isListening, interim, isSupported: sttSupported, start: startListening, stop: stopListening } =
    useSpeechRecognition((transcript) => setInput((prev) => (prev ? prev + ' ' + transcript : transcript)))

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  const historyForApi = useCallback((): ChatMessage[] => {
    return messages
      .filter((m) => m.role !== 'system' && !m.tool)
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
      for await (const chunk of streamTutorChat(anthropicKey, student, subject, historyForApi(), childMessage, drawingImage, abortRef.current.signal)) {
        if (chunk.type === 'text') {
          fullText += chunk.content
          setMessages((prev) => prev.map((m) => (m.id === assistantId ? { ...m, content: fullText } : m)))
        } else if (chunk.type === 'tool') {
          setMessages((prev) => [...prev, { id: `tool-${Date.now()}-${Math.random()}`, role: 'assistant', content: chunk.content, tool: chunk.tool }])
          if (ttsEnabled) speak(chunk.content)
        } else if (chunk.type === 'done') {
          break
        }
      }
      if (ttsEnabled && fullText) speak(fullText)
    } catch (err) {
      // Drop the empty placeholder bubble on failure — an error message alone
      // reads better than an empty "Bede" bubble sitting above it.
      setMessages((prev) => prev.filter((m) => m.id !== assistantId || m.content))
      if (err instanceof Error && err.name !== 'AbortError') {
        setMessages((prev) => [...prev, { id: `err-${Date.now()}`, role: 'system', content: `⚠️ ${err.message}` }])
      }
    } finally {
      setIsStreaming(false)
    }
  }, [anthropicKey, student, subject, historyForApi, ttsEnabled, speak])

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

  return (
    <div className="flex flex-col h-screen bg-parchment-50">
      <header className="bg-white border-b border-navy-100 shrink-0 h-14 flex items-center px-4 gap-3">
        <img src="/bede-icon.png" alt="Bede" className="w-8 h-8 rounded-full object-cover" />
        <div className="flex-1 min-w-0">
          <span className="text-navy-700 font-semibold text-sm">Bede</span>
          <span className="text-gray-400 text-xs ml-2">with {student.name}</span>
        </div>
        <select
          value={subject}
          onChange={(e) => setSubject(e.target.value as Subject)}
          className="text-xs border border-navy-200 rounded-lg px-2 py-1.5 bg-white"
        >
          {SUBJECTS.map((s) => <option key={s} value={s}>{SUBJECT_LABELS[s]}</option>)}
        </select>
        <button onClick={onReset} className="text-xs text-gray-400 hover:text-gray-600 underline">Reset</button>
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
        {messages.map((msg) => (
          <MessageBubble key={msg.id} msg={msg} studentName={student.name} />
        ))}
        {isStreaming && messages.at(-1)?.content === '' && (
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
          <button onClick={() => setShowCanvas(true)} disabled={isStreaming} className="p-2.5 rounded-lg bg-navy-100 text-navy-600 hover:bg-navy-200 disabled:opacity-40 transition-colors flex-shrink-0">
            <PenLine size={18} />
          </button>
          <button onClick={() => (ttsEnabled ? (setTtsEnabled(false), stopSpeech()) : setTtsEnabled(true))} className={`p-2.5 rounded-lg transition-colors flex-shrink-0 ${ttsEnabled ? 'bg-navy-100 text-navy-600' : 'bg-gray-100 text-gray-400'}`}>
            {ttsEnabled ? (isSpeaking ? <Volume2 size={18} className="animate-pulse" /> : <Volume2 size={18} />) : <VolumeX size={18} />}
          </button>
          {sttSupported && (
            <button onClick={toggleMic} disabled={isStreaming} className={`p-2.5 rounded-lg transition-colors flex-shrink-0 ${isListening ? 'bg-red-500 text-white animate-pulse' : 'bg-navy-100 text-navy-600 hover:bg-navy-200 disabled:opacity-40'}`}>
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
          <button onClick={send} disabled={isStreaming || (!input.trim() && !pendingDrawing)} className="p-2.5 rounded-lg bg-navy-500 text-white hover:bg-navy-600 disabled:opacity-40 transition-colors flex-shrink-0">
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
  if (msg.tool) {
    const accent: Record<string, string> = {
      request_narration: 'border-l-[3px] border-amber-400 bg-amber-50/70',
      offer_socratic_hint: 'border-l-[3px] border-navy-300 bg-navy-50/70',
      celebrate_discovery: 'border-l-[3px] border-emerald-400 bg-emerald-50/70',
      connect_to_faith: 'border-l-[3px] border-gold-400 bg-gold-50/70',
    }
    return <div className={`pl-3 pr-4 py-2.5 rounded-r-xl text-sm leading-relaxed text-gray-700 ${accent[msg.tool] ?? 'border-l-[3px] border-gray-300 bg-gray-50/70'}`}>{msg.content}</div>
  }
  const isUser = msg.role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${isUser ? 'bg-navy-500 text-white rounded-br-sm' : 'bg-white border border-navy-100 text-gray-800 rounded-bl-sm shadow-sm'}`}>
        {!isUser && <div className="text-xs font-semibold text-navy-600 mb-1">Bede</div>}
        {isUser && <div className="text-xs font-semibold text-navy-100 mb-1">{studentName}</div>}
        <div className="whitespace-pre-wrap">{msg.content}</div>
      </div>
    </div>
  )
}

function PinScreen({ studentName, onVerified }: { studentName: string; onVerified: () => void }) {
  const [entered, setEntered] = useState('')
  const [error, setError] = useState('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const storedPin = localStorage.getItem(LS_KEYS.pin) ?? ''
    if (entered.trim() === storedPin) {
      onVerified()
    } else {
      setError('Incorrect PIN. Try again.')
      setEntered('')
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-parchment-100 via-navy-50 to-gold-100 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-lg border border-navy-100 w-full max-w-sm p-8">
        <div className="text-center mb-6">
          <div className="w-14 h-14 mx-auto mb-3 rounded-full bg-navy-100 flex items-center justify-center">
            <Lock size={24} className="text-navy-600" />
          </div>
          <h1 className="text-xl font-display font-bold text-gray-800">Welcome, {studentName}</h1>
          <p className="text-sm text-gray-500 mt-1">Enter your PIN to begin</p>
        </div>

        <div className="flex items-start gap-2.5 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2.5 mb-5 text-xs text-amber-800">
          <ShieldAlert size={16} className="flex-shrink-0 mt-0.5" />
          <p>
            <strong>UI demonstration only.</strong> This shows what the real app's login
            <em> looks</em> like — it is not the real security model. The production app checks
            the PIN server-side, then verifies the child's actual voice before granting access;
            this demo only compares text stored in your own browser, which is not a real
            safeguard.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          <input
            type="password" inputMode="numeric" autoFocus
            className="input text-center text-lg tracking-widest"
            value={entered} onChange={(e) => setEntered(e.target.value)}
            placeholder="••••"
          />
          {error && <p className="text-sm text-red-600 text-center">{error}</p>}
          <button type="submit" disabled={!entered.trim()} className="w-full py-3 bg-navy-500 text-white rounded-lg font-medium hover:bg-navy-600 disabled:opacity-40 transition-colors">
            Continue
          </button>
        </form>
      </div>
    </div>
  )
}

export default function App() {
  const [student, setStudent] = useState<StudentProfile | null>(() => {
    const raw = localStorage.getItem(LS_KEYS.student)
    const key = localStorage.getItem(LS_KEYS.anthropicKey)
    if (raw && key) {
      try { return JSON.parse(raw) } catch { return null }
    }
    return null
  })
  // Resets on every reload/new tab, same as the real app requiring login each session —
  // never persisted, since persisting it would defeat the point of even a cosmetic gate.
  const [pinVerified, setPinVerified] = useState(false)

  const handleReset = () => {
    Object.values(LS_KEYS).forEach((k) => localStorage.removeItem(k))
    setStudent(null)
    setPinVerified(false)
  }

  if (!student) {
    return <SetupScreen onReady={() => setStudent(JSON.parse(localStorage.getItem(LS_KEYS.student)!))} />
  }
  if (localStorage.getItem(LS_KEYS.pin) && !pinVerified) {
    return <PinScreen studentName={student.name} onVerified={() => setPinVerified(true)} />
  }
  return <ChatScreen student={student} onReset={handleReset} />
}
