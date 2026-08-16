import { useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { ArrowLeft, FlaskConical, Send, Loader2, AlertCircle, ChevronDown, ChevronUp, Volume2, VolumeX } from 'lucide-react'
import { useSessionStore } from '../store/sessionStore'
import { streamSandboxChat } from '../services/api'
import { renderEmphasis } from '../utils/renderEmphasis'
import { useTextToSpeech } from '../hooks/useTextToSpeech'
import type { ChatMessage } from '../types'

// Nothing on this page is persisted anywhere — no sessionStorage, no
// database, no audit-logged content. The PIN and custom instructions live
// only in this component's own state and are gone the moment the tab
// closes or reloads, matching the backend's "nothing written to the
// database" guarantee in routers/sandbox.py.
export default function Sandbox() {
  const navigate = useNavigate()
  const { token } = useSessionStore()

  const [sandboxPin, setSandboxPin] = useState('')
  const [customInstructions, setCustomInstructions] = useState('')
  const [settingsOpen, setSettingsOpen] = useState(true)

  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState('')
  const abortRef = useRef<AbortController | null>(null)

  // ── Text-to-speech: hear Bede's actual voice while previewing a response ──
  // No sessionConfig here (this page persists nothing at all — see the file
  // docstring above), so unlike SocraticChat.tsx's toggleTTS this has no
  // per-student preference to save server-side; enabled/disabled just lives
  // in this component's own state like everything else on this page, and
  // resets to on (matching a real child session's own default) on reload.
  // The whole point of this page is previewing what the child will actually
  // hear before they hear it — muted by default would work against that.
  const { speak, stop: stopSpeech, toggle: toggleTTS, isSpeaking, enabled: ttsEnabled } = useTextToSpeech(token, true)

  const handleSend = async () => {
    const text = input.trim()
    if (!text || streaming || !token) return
    if (!sandboxPin.trim()) {
      setError('Enter the sandbox PIN above first.')
      setSettingsOpen(true)
      return
    }

    // A previous answer may still be mid-speech — this app already treats a
    // new turn as implicitly ending the last one's audio (see SocraticChat's
    // own barge-in handling); a rapid-fire testing tool is exactly the case
    // where a parent fires off a second question before the first finishes.
    stopSpeech()

    setError('')
    const history = messages
    const userMsg: ChatMessage = { role: 'user', content: text }
    setMessages([...history, userMsg, { role: 'assistant', content: '' }])
    setInput('')
    setStreaming(true)

    const controller = new AbortController()
    abortRef.current = controller

    try {
      let assembled = ''
      for await (const chunk of streamSandboxChat(
        token, sandboxPin, history, text, customInstructions, controller.signal
      )) {
        if (chunk.type === 'text' && chunk.content) {
          assembled += chunk.content
          setMessages((prev) => {
            const next = [...prev]
            next[next.length - 1] = { role: 'assistant', content: assembled }
            return next
          })
        }
      }
      // Speak once, after the full reply has streamed in — this page shows
      // one plain assistant bubble per turn rather than SocraticChat's
      // tool-card-interleaved segments, so there is only ever one thing to
      // queue, unlike that page's speechSegments accumulator.
      if (assembled.trim()) speak(assembled)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong')
      setMessages((prev) => prev.slice(0, -1)) // drop the empty assistant placeholder
    } finally {
      setStreaming(false)
    }
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    // h-dvh, not h-screen — see TutorSession.tsx's identical fix for why
    // 100vh gets the mobile browser's collapsing address-bar chrome wrong,
    // pushing this fixed header into the page's own scroll.
    <div className="h-dvh flex flex-col bg-parchment-50">
      {/* Header */}
      <header className="shrink-0 bg-white border-b border-navy-100 px-4 py-3 flex items-center gap-3">
        <button
          onClick={() => navigate('/pod')}
          className="p-2 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-50 transition-colors"
          aria-label="Back to Pod Dashboard"
        >
          <ArrowLeft size={18} />
        </button>
        <div className="w-8 h-8 rounded-full bg-sage-100 flex items-center justify-center flex-shrink-0">
          <FlaskConical size={16} className="text-sage-600" />
        </div>
        <div className="min-w-0 flex-1">
          <h1 className="text-base font-display font-bold text-gray-800 leading-tight">Ask Bede — Sandbox</h1>
          <p className="text-xs text-gray-500 leading-tight">
            Direct answers, not Socratic — nothing here is saved
          </p>
        </div>
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
      </header>

      {/* Settings — PIN + custom instructions */}
      <div className="shrink-0 bg-white border-b border-navy-100">
        <button
          onClick={() => setSettingsOpen((o) => !o)}
          className="w-full flex items-center justify-between px-4 py-2 text-xs font-semibold text-gray-500 hover:bg-gray-50 transition-colors"
        >
          <span>Sandbox settings</span>
          {settingsOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>
        {settingsOpen && (
          <div className="px-4 pb-4 space-y-3 max-w-2xl">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Sandbox PIN</label>
              <input
                type="password"
                value={sandboxPin}
                onChange={(e) => setSandboxPin(e.target.value)}
                placeholder="Enter the SANDBOX_PIN configured for this deployment"
                className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-sage-300"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">
                Custom instructions <span className="font-normal text-gray-400">(your own test lesson content — never saved, never affects real students)</span>
              </label>
              <textarea
                value={customInstructions}
                onChange={(e) => setCustomInstructions(e.target.value)}
                placeholder="e.g. Try responding as if teaching a 3rd-grade fractions lesson on equivalent fractions..."
                rows={3}
                className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-sage-300 resize-none"
              />
            </div>
          </div>
        )}
      </div>

      {/* Chat */}
      <main className="flex-1 overflow-y-auto px-4 py-4">
        <div className="max-w-2xl mx-auto space-y-3">
          {messages.length === 0 && (
            <p className="text-sm text-gray-400 text-center mt-12">
              Ask Bede anything. No need to guess through questions, and you can switch topics freely.
            </p>
          )}
          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div
                className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm whitespace-pre-wrap ${
                  m.role === 'user'
                    ? 'bg-navy-500 text-white'
                    : 'bg-white border border-sage-100 text-gray-800'
                }`}
              >
                {m.content ? renderEmphasis(m.content) : (streaming && i === messages.length - 1 && (
                  <Loader2 size={14} className="animate-spin text-gray-400" />
                ))}
              </div>
            </div>
          ))}
          {error && (
            <p className="text-xs text-red-600 flex items-center gap-1 justify-center">
              <AlertCircle size={12} /> {error}
            </p>
          )}
        </div>
      </main>

      {/* Input */}
      <div className="shrink-0 border-t border-navy-100 bg-white p-3">
        <div className="max-w-2xl mx-auto flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Ask Bede anything…"
            rows={1}
            disabled={streaming}
            className="flex-1 px-3 py-2.5 text-sm border border-gray-200 rounded-xl resize-none focus:outline-none focus:ring-2 focus:ring-sage-300 disabled:opacity-50"
          />
          <button
            onClick={handleSend}
            disabled={streaming || !input.trim()}
            className="p-2.5 bg-navy-500 text-white rounded-xl hover:bg-navy-600 transition-colors disabled:opacity-40"
          >
            {streaming ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
          </button>
        </div>
      </div>
    </div>
  )
}
