import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import en from './locales/en.json'
import es from './locales/es.json'

// Deployment-wide, not per-request: a self-hosted family instance runs in
// exactly one language, chosen once at setup via VITE_LOCALE (same
// build-time-baked pattern as VITE_DEMO_API_BASE in demo/src/api.ts) — not
// a runtime switcher. See docs/LOCALIZATION.md. The public demo, which
// serves visitors worldwide at once, needs its own runtime switcher instead
// and is out of scope for this resource bundle.
const locale = (import.meta.env.VITE_LOCALE as string | undefined) || 'en'

i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    es: { translation: es },
  },
  lng: locale,
  fallbackLng: 'en',
  interpolation: {
    escapeValue: false, // React already escapes; double-escaping breaks {{name}} with special chars
  },
})

export default i18n
