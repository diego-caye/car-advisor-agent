import { Brain, Wrench } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { Badge } from '@/components/ui/badge'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

import type { ModelOption } from '../../api/types'

const PROVIDER_LABEL: Record<string, string> = {
  ollama: 'local',
  gemini: 'API',
}

type Props = {
  models: ModelOption[]
  value: string | null
  disabled: boolean
  onChange: (modelId: string) => void
}

export function ModelSelect({ models, value, disabled, onChange }: Props) {
  const { t } = useTranslation()
  // With only one option the selector adds nothing: the model is already
  // visible in the dev panel, in the turn metrics.
  if (models.length < 2) return null

  const current = models.find((model) => model.id === value) ?? models[0]
  if (!current) return null

  return (
    <Select value={current.id} disabled={disabled} onValueChange={onChange}>
      <SelectTrigger
        size="sm"
        aria-label={t('modelSelect.ariaLabel')}
        title={`${current.model} · ${current.provider}`}
        className="min-w-[9.5rem]"
      >
        <SelectValue />
      </SelectTrigger>
      {/* "item-aligned" (the default value) overlays the menu on top of the
          trigger to align the selected option, like a native <select>; in a
          narrow header that covered the selector itself. "popper" opens it
          below, like any other dropdown menu. */}
      <SelectContent position="popper" align="start" sideOffset={6}>
        {models.map((model) => (
          // Unconfigured options are shown disabled instead of hidden: this
          // way it's visible what's available and why it can't be used.
          <SelectItem key={model.id} value={model.id} disabled={!model.available}>
            <span className="flex items-center gap-1.5">
              {model.label}
              <Badge variant="outline" className="text-[10px]">
                {PROVIDER_LABEL[model.provider] ?? model.provider}
              </Badge>
              {/* The model's real capabilities, discovered against Ollama
                  (/api/show) for local options — not every variant of the
                  same model has them equally: qwen3:4b thinks and
                  qwen3:4b-instruct doesn't, for example. */}
              {model.supports_thinking && (
                <Brain className="text-muted-foreground size-3" aria-hidden="true">
                  <title>{t('modelSelect.canReason')}</title>
                </Brain>
              )}
              {model.supports_tools && (
                <Wrench className="text-muted-foreground size-3" aria-hidden="true">
                  <title>{t('modelSelect.canUseTools')}</title>
                </Wrench>
              )}
              {!model.available && (
                <span className="text-muted-foreground text-[10px]">{t('modelSelect.notConfigured')}</span>
              )}
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
