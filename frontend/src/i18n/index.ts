import i18n from 'i18next'
import LanguageDetector from 'i18next-browser-languagedetector'
import { initReactI18next } from 'react-i18next'

import en from './locales/en.json'
import es from './locales/es.json'

export const LANGUAGE_STORAGE_KEY = 'asesor.language'

// Keeps the <html lang> attribute in sync with whatever the detector
// resolved or the user picked -- matters for screen readers and SEO, not
// for layout, so there's no flash-of-wrong-language to guard against like
// the dark-mode inline script does.
function applyHtmlLang(language: string) {
  document.documentElement.lang = language
}

i18n.on('languageChanged', applyHtmlLang)

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      es: { translation: es },
    },
    // Mirrors the agent's own default (spec 05 LANGUAGE): Peru Spanish when
    // the signal is genuinely unresolvable, not a thin reason to guess English.
    fallbackLng: 'es',
    supportedLngs: ['en', 'es'],
    nonExplicitSupportedLngs: true,
    interpolation: { escapeValue: false },
    detection: {
      order: ['localStorage', 'navigator'],
      caches: ['localStorage'],
      lookupLocalStorage: LANGUAGE_STORAGE_KEY,
    },
  })
  .then(() => applyHtmlLang(i18n.resolvedLanguage ?? 'es'))

export default i18n
