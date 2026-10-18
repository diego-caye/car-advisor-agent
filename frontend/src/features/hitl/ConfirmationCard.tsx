import { CircleCheckBig, CircleX, UserRoundCheck } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

import { channelLabel, reasonLabel } from '../chat/labels'
import type { Confirmation, DeclinedConfirmation, Handoff } from '../chat/reducer'

type Props = {
  confirmation: Confirmation
  busy: boolean
  onAnswer: (approved: boolean) => void
}

export function ConfirmationCard({ confirmation, busy, onAnswer }: Props) {
  const { t } = useTranslation()
  const reason = reasonLabel(t, confirmation.reason)
  const channel = confirmation.preferred_channel
    ? channelLabel(t, confirmation.preferred_channel)
    : null

  return (
    <Card className="border-primary/60 bg-raised mx-auto w-full max-w-2xl gap-3 py-4">
      <CardHeader className="gap-1">
        <CardTitle className="flex items-center gap-2 text-[15px]">
          <UserRoundCheck className="text-primary size-4" aria-hidden="true" />
          {t('confirmation.title')}
        </CardTitle>
        <CardDescription>{t('confirmation.description', { reason })}</CardDescription>
      </CardHeader>

      <CardContent className="flex flex-col gap-3">
        <p className="bg-card rounded-lg px-3 py-2 text-sm">{confirmation.resumen}</p>

        {channel && (
          <p className="text-muted-foreground text-xs">
            {t('confirmation.contactedVia', { channel })}
          </p>
        )}

        <div className="flex flex-wrap gap-2">
          <Button type="button" size="lg" onClick={() => onAnswer(true)} disabled={busy}>
            {t('confirmation.confirm')}
          </Button>
          <Button
            type="button"
            size="lg"
            variant="outline"
            onClick={() => onAnswer(false)}
            disabled={busy}
          >
            {t('confirmation.declineNow')}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

export function HandoffNotice({ handoff }: { handoff: Handoff }) {
  const { t } = useTranslation()

  return (
    <p
      className="border-ok/40 bg-card text-ok mx-auto flex max-w-2xl items-center gap-2 rounded-lg border px-4 py-2.5 text-sm"
      role="status"
    >
      <CircleCheckBig className="size-4 shrink-0" aria-hidden="true" />
      {t('confirmation.title')} ·{' '}
      {handoff.ya_existia ? t('confirmation.alreadyHadOne') : t('confirmation.yesHandoff')} ·{' '}
      <span className="tabular font-semibold">{handoff.ticket}</span>
    </p>
  )
}

// Declining doesn't create anything (spec 03 §3), so unlike HandoffNotice
// there's no ticket to show -- just the echo of the question and the
// decision, so it doesn't look like the card simply vanished on its own.
export function DeclinedNotice({ declined }: { declined: DeclinedConfirmation }) {
  const { t } = useTranslation()
  const reason = reasonLabel(t, declined.reason)

  return (
    <p
      className="text-muted-foreground bg-card mx-auto flex max-w-2xl items-center gap-2 rounded-lg border px-4 py-2.5 text-sm"
      role="status"
    >
      <CircleX className="size-4 shrink-0" aria-hidden="true" />
      {t('confirmation.declinedNotice', { reason })}
    </p>
  )
}
