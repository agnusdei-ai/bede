import { ShieldAlert } from 'lucide-react'
import { AgnusDeiLogo, TrademarkNotice } from './BedeMark'

/**
 * Gates the entry screen behind an explicit "I understand and agree" —
 * see useConsent.ts for the localStorage flag this sets. Replaces the old
 * passive amber notice box (which stayed, but is no longer the only place
 * this is disclosed): a visitor now has to actively acknowledge this
 * before "Generate my code" is even reachable, not just have it sit next
 * to the button as skippable small print.
 *
 * Deliberately plain, honest language over anything that reads like a
 * legal document — this is a beta demo notice, not a EULA. The full
 * Privacy Notice it links to (public/privacy.html — a static page, not a
 * React route, so it works standalone and survives a JS failure) has the
 * complete picture; this is the summary someone will actually read.
 */
export default function ConsentModal({ onAgree }: { onAgree: () => void }) {
  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-lg border border-navy-100 w-full max-w-md p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center gap-2 mb-1">
          <ShieldAlert size={20} className="text-amber-600 shrink-0" />
          <h1 className="text-lg font-display font-bold text-gray-800">Before you begin</h1>
        </div>
        <p className="text-xs text-gray-500 mb-4">This is a public beta — please read this first.</p>

        <ul className="space-y-3 text-sm text-gray-700 mb-5">
          <li className="flex gap-2.5">
            <span className="text-navy-400 font-bold shrink-0">•</span>
            <span>
              <strong className="text-gray-800">Your conversation is never stored.</strong> Nothing you or your
              learner says is saved, ever.
            </span>
          </li>
          <li className="flex gap-2.5">
            <span className="text-navy-400 font-bold shrink-0">•</span>
            <span>
              <strong className="text-gray-800">Anonymized patterns may be reviewed</strong> — which teaching
              techniques were used, never what was said — to help us improve Bede.
            </span>
          </li>
          <li className="flex gap-2.5">
            <span className="text-navy-400 font-bold shrink-0">•</span>
            <span>
              <strong className="text-gray-800">Name and grade personalize this session</strong> — kept up to 6
              hours (sooner if you log out), then deleted automatically. Never part of any permanent record.
            </span>
          </li>
          <li className="flex gap-2.5">
            <span className="text-navy-400 font-bold shrink-0">•</span>
            <span>
              <strong className="text-gray-800">Feedback is optional.</strong> Parents/guardians may leave an
              email for follow-up — we never ask a child for their own.
            </span>
          </li>
        </ul>

        <a
          href={`${import.meta.env.BASE_URL}privacy.html`}
          target="_blank"
          rel="noopener noreferrer"
          className="block text-xs text-navy-600 underline hover:text-navy-800 mb-5"
        >
          Read the full Privacy Notice, including our COPPA parental notice
        </a>

        <button
          onClick={onAgree}
          className="w-full py-3 bg-navy-500 text-white rounded-lg font-semibold text-sm hover:bg-navy-600 transition-colors"
        >
          I understand and agree — let's begin
        </button>

        <div className="flex flex-col items-center gap-1.5 mt-5">
          <AgnusDeiLogo className="h-7 opacity-70" />
          <TrademarkNotice className="text-center" />
        </div>
      </div>
    </div>
  )
}
