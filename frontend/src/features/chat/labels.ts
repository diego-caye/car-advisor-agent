import type { TFunction } from 'i18next'

// Small wrappers instead of static Record<string, string> maps: the label now
// depends on the active UI language (i18n), so it has to be resolved through
// `t` at render time instead of being a plain module-level constant.
export function stageLabel(t: TFunction, stage: string): string {
  return t(`stage.${stage}`, { defaultValue: stage })
}

export function reasonLabel(t: TFunction, reason: string | undefined): string {
  if (!reason) return t('reason.default')
  return t(`reason.${reason}`, { defaultValue: t('reason.default') })
}

export function channelLabel(t: TFunction, channel: string): string {
  return t(`channel.${channel}`, { defaultValue: channel })
}

export function toolActivityLabel(t: TFunction, name: string): string {
  return t(`toolActivity.${name}`, { defaultValue: t('messageList.working') })
}

export const LEAD_FIELDS: { key: string; labelKey: string }[] = [
  { key: 'name', labelKey: 'leadField.name' },
  { key: 'primary_use', labelKey: 'leadField.primary_use' },
  { key: 'vehicle_type_interest', labelKey: 'leadField.vehicle_type_interest' },
  { key: 'powertrain_interest', labelKey: 'leadField.powertrain_interest' },
  { key: 'interest_level', labelKey: 'leadField.interest_level' },
  { key: 'preferred_channel', labelKey: 'leadField.preferred_channel' },
]
