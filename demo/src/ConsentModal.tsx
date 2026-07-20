import { useTranslation, Trans } from 'react-i18next'
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
 * Privacy Notice it links to (public/privacy.html, or public/privacy.es.html
 * when i18n.language is "es" — a static page, not a React route, so it
 * works standalone and survives a JS failure) has the complete picture;
 * this is the summary someone will actually read.
 */
export default function ConsentModal({ onAgree }: { onAgree: () => void }) {
  const { t, i18n } = useTranslation()
  const privacyHref = `${import.meta.env.BASE_URL}${i18n.language === 'es' ? 'privacy.es.html' : 'privacy.html'}`

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-lg border border-navy-100 w-full max-w-md p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center gap-2 mb-1">
          <ShieldAlert size={20} className="text-amber-600 shrink-0" />
          <h1 className="text-lg font-display font-bold text-gray-800">{t('consent.beforeYouBegin')}</h1>
        </div>
        <p className="text-xs text-gray-500 mb-4">{t('consent.betaNotice')}</p>

        <ul className="space-y-3 text-sm text-gray-700 mb-5">
          <li className="flex gap-2.5">
            <span className="text-navy-400 font-bold shrink-0">•</span>
            <span>
              <Trans i18nKey="consent.bullet1" components={{ strong: <strong className="text-gray-800" /> }} />
            </span>
          </li>
          <li className="flex gap-2.5">
            <span className="text-navy-400 font-bold shrink-0">•</span>
            <span>
              <Trans i18nKey="consent.bullet2" components={{ strong: <strong className="text-gray-800" /> }} />
            </span>
          </li>
          <li className="flex gap-2.5">
            <span className="text-navy-400 font-bold shrink-0">•</span>
            <span>
              <Trans i18nKey="consent.bullet3" components={{ strong: <strong className="text-gray-800" /> }} />
            </span>
          </li>
          <li className="flex gap-2.5">
            <span className="text-navy-400 font-bold shrink-0">•</span>
            <span>
              <Trans i18nKey="consent.bullet4" components={{ strong: <strong className="text-gray-800" /> }} />
            </span>
          </li>
        </ul>

        <a
          href={privacyHref}
          target="_blank"
          rel="noopener noreferrer"
          className="block text-xs text-navy-600 underline hover:text-navy-800 mb-5"
        >
          {t('consent.readPrivacyNotice')}
        </a>

        <button
          onClick={onAgree}
          className="w-full py-3 bg-navy-500 text-white rounded-lg font-semibold text-sm hover:bg-navy-600 transition-colors"
        >
          {t('consent.agree')}
        </button>

        <div className="flex flex-col items-center gap-1.5 mt-5">
          <AgnusDeiLogo className="h-7 opacity-70" />
          <TrademarkNotice className="text-center" />
        </div>
      </div>
    </div>
  )
}
