import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import en from './locales/en.json'
import es from './locales/es.json'

// Mirrors homeschool-tutor/src/i18n/index.ts's per-login model (see
// docs/LOCALIZATION.md) — both locale bundles are always loaded, and
// CodeScreen.tsx calls i18n.changeLanguage() the moment a visitor taps the
// toggle, same as Login.tsx there. Unlike homeschool-tutor, the demo has no
// persisted session store to restore a locale from on reload — sessionStorage
// (CODE_SCREEN_LOCALE_KEY in CodeScreen's own file) fills that role instead,
// consistent with how this file already persists the visitor's name/grade
// choices across a reload within the same tab.
i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    es: { translation: es },
  },
  lng: 'en',
  fallbackLng: 'en',
  interpolation: {
    escapeValue: false, // React already escapes; double-escaping breaks {{name}} with special chars
  },
})

export default i18n
