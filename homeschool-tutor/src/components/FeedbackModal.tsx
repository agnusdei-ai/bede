import { useState } from 'react'
import { X, MessageSquare, Star, Check, Loader2 } from 'lucide-react'
import { submitFeedback, type FeedbackCategory } from '../services/api'

const FEEDBACK_CATEGORIES: { value: FeedbackCategory; label: string }[] = [
  { value: 'cx', label: 'Overall experience' },
  { value: 'ux', label: 'Usability / interface' },
  { value: 'content_quality', label: "Bede's teaching quality" },
  { value: 'other', label: 'Something else' },
]

/**
 * Beta CX/UX/content-quality feedback, routed to the operator's own inbox —
 * see homeschool-api/routers/feedback.py. Never persisted server-side beyond
 * that one email. Open from a live session (not just a post-session summary
 * screen) since a rough edge is easiest to describe the moment it happens.
 */
export default function FeedbackModal({ token, onClose }: { token: string; onClose: () => void }) {
  const [category, setCategory] = useState<FeedbackCategory>('cx')
  const [rating, setRating] = useState(0)
  const [message, setMessage] = useState('')
  const [contactEmail, setContactEmail] = useState('')
  const [status, setStatus] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle')
  const [errorMsg, setErrorMsg] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setStatus('sending')
    setErrorMsg('')
    try {
      await submitFeedback(token, category, message.trim(), rating || undefined, contactEmail || undefined)
      setStatus('sent')
    } catch (err) {
      setStatus('error')
      setErrorMsg(err instanceof Error ? err.message : 'Could not send feedback right now.')
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-lg border border-navy-100 w-full max-w-sm p-6 relative">
        <button onClick={onClose} className="absolute top-3 right-3 text-gray-400 hover:text-gray-600" aria-label="Close">
          <X size={18} />
        </button>

        {status === 'sent' ? (
          <div className="text-center py-4">
            <Check size={28} className="mx-auto mb-3 text-green-600" />
            <p className="text-sm font-semibold text-gray-800 mb-1">Thank you!</p>
            <p className="text-xs text-gray-500">Your feedback was sent — it genuinely helps shape what's next.</p>
            <button onClick={onClose} className="mt-5 w-full py-2.5 bg-navy-100 text-navy-700 rounded-xl font-semibold text-sm hover:bg-navy-200 transition-colors">
              Close
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit}>
            <div className="flex items-center gap-1.5 mb-4">
              <MessageSquare size={16} className="text-navy-500" />
              <h2 className="text-sm font-display font-bold text-gray-800">Share feedback with the team</h2>
            </div>

            <label className="block text-xs font-semibold text-navy-500 uppercase tracking-wide mb-1">What's this about?</label>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value as FeedbackCategory)}
              className="w-full text-sm border border-navy-200 rounded-lg px-3 py-2 bg-white cursor-pointer mb-3 focus:outline-none focus:ring-2 focus:ring-navy-400"
            >
              {FEEDBACK_CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>

            <label className="block text-xs font-semibold text-navy-500 uppercase tracking-wide mb-1">
              Rating <span className="font-normal normal-case text-gray-400">(optional)</span>
            </label>
            <div className="flex gap-1 mb-3">
              {[1, 2, 3, 4, 5].map((n) => (
                <button
                  type="button"
                  key={n}
                  onClick={() => setRating(rating === n ? 0 : n)}
                  aria-label={`${n} star${n > 1 ? 's' : ''}`}
                  className="p-0.5"
                >
                  <Star size={20} className={n <= rating ? 'fill-gold-400 text-gold-500' : 'text-gray-300'} />
                </button>
              ))}
            </div>

            <label htmlFor="feedback-message" className="block text-xs font-semibold text-navy-500 uppercase tracking-wide mb-1">
              Your feedback
            </label>
            <textarea
              id="feedback-message"
              required
              maxLength={2000}
              rows={4}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="What worked, what didn't, what surprised you…"
              className="w-full text-sm border border-navy-200 rounded-lg px-3 py-2 mb-3 resize-none focus:outline-none focus:ring-2 focus:ring-navy-400"
            />

            <label htmlFor="feedback-email" className="block text-xs font-semibold text-navy-500 uppercase tracking-wide mb-1">
              Email <span className="font-normal normal-case text-gray-400">(optional — only if you want a reply)</span>
            </label>
            <input
              id="feedback-email"
              type="email"
              value={contactEmail}
              onChange={(e) => setContactEmail(e.target.value)}
              placeholder="you@example.com"
              className="w-full text-sm border border-navy-200 rounded-lg px-3 py-2 mb-4 focus:outline-none focus:ring-2 focus:ring-navy-400"
            />

            {status === 'error' && <p className="text-xs text-red-600 mb-3">{errorMsg}</p>}

            <button
              type="submit"
              disabled={status === 'sending' || !message.trim()}
              className="w-full py-2.5 bg-navy-500 text-white rounded-xl font-semibold text-sm hover:bg-navy-600 transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {status === 'sending' ? <Loader2 size={16} className="animate-spin" /> : 'Send feedback'}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}
