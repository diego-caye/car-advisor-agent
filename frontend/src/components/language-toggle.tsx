import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'

export function LanguageToggle() {
  const { t, i18n } = useTranslation()
  const isEnglish = i18n.resolvedLanguage === 'en'

  function toggle() {
    void i18n.changeLanguage(isEnglish ? 'es' : 'en')
  }

  return (
    <Button
      type="button"
      variant="outline"
      size="icon-sm"
      onClick={toggle}
      aria-label={isEnglish ? t('languageToggle.switchToSpanish') : t('languageToggle.switchToEnglish')}
      title={isEnglish ? t('languageToggle.switchToSpanish') : t('languageToggle.switchToEnglish')}
    >
      <span className="text-[11px] font-semibold" aria-hidden="true">
        {isEnglish ? 'ES' : 'EN'}
      </span>
    </Button>
  )
}
