import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import en from './locales/en.json'
import es from './locales/es.json'

// Per-login, not build-time: which language a session runs in is picked at
// the login screen itself (Login.tsx's English/Español toggle, only shown
// when GET /auth/locales says this deployment offers one) and applied at
// runtime via i18n.changeLanguage() — see Login.tsx and guards/AppShell.tsx
// (which restores it from the persisted session store on a page refresh).
// VITE_LOCALE only sets the INITIAL language before any of that has had a
// chance to run — the very first paint of the login screen itself, before
// a stored locale can be read — not a deployment-wide lock the way it used
// to be. Both resource bundles are always loaded regardless, so switching
// is instant with no network request. See docs/LOCALIZATION.md.
const initialLocale = (import.meta.env.VITE_LOCALE as string | undefined) || 'en'

i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    es: { translation: es },
  },
  lng: initialLocale,
  fallbackLng: 'en',
  interpolation: {
    escapeValue: false, // React already escapes; double-escaping breaks {{name}} with special chars
  },
})

export default i18n
