import { CircleCheckBig, CircleX, UserRoundCheck } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

import { CHANNEL_LABEL, REASON_LABEL } from '../chat/labels'
import type { Confirmation, DeclinedConfirmation, Handoff } from '../chat/reducer'

type Props = {
  confirmation: Confirmation
  busy: boolean
  onAnswer: (approved: boolean) => void
}

export function ConfirmationCard({ confirmation, busy, onAnswer }: Props) {
  const reason = REASON_LABEL[confirmation.reason] ?? 'hablar con un asesor'
  const channel = confirmation.preferred_channel
    ? (CHANNEL_LABEL[confirmation.preferred_channel] ?? confirmation.preferred_channel)
    : null

  return (
    <Card className="border-primary/60 bg-raised mx-auto w-full max-w-2xl gap-3 py-4">
      <CardHeader className="gap-1">
        <CardTitle className="flex items-center gap-2 text-[15px]">
          <UserRoundCheck className="text-primary size-4" aria-hidden="true" />
          ¿Te derivamos con un asesor?
        </CardTitle>
        <CardDescription>Luis quiere pasar tu caso a una persona para {reason}.</CardDescription>
      </CardHeader>

      <CardContent className="flex flex-col gap-3">
        <p className="bg-card rounded-lg px-3 py-2 text-sm">{confirmation.resumen}</p>

        {channel && (
          <p className="text-muted-foreground text-xs">Te contactarían por {channel}.</p>
        )}

        <div className="flex flex-wrap gap-2">
          <Button type="button" size="lg" onClick={() => onAnswer(true)} disabled={busy}>
            Confirmar solicitud
          </Button>
          <Button
            type="button"
            size="lg"
            variant="outline"
            onClick={() => onAnswer(false)}
            disabled={busy}
          >
            Ahora no
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

export function HandoffNotice({ handoff }: { handoff: Handoff }) {
  return (
    <p
      className="border-ok/40 bg-card text-ok mx-auto flex max-w-2xl items-center gap-2 rounded-lg border px-4 py-2.5 text-sm"
      role="status"
    >
      <CircleCheckBig className="size-4 shrink-0" aria-hidden="true" />
      ¿Te derivamos con un asesor? · {handoff.ya_existia ? 'Ya tenías una solicitud en curso' : 'Sí, derivar'} ·{' '}
      <span className="tabular font-semibold">{handoff.ticket}</span>
    </p>
  )
}

// Declining doesn't create anything (spec 03 §3), so unlike HandoffNotice
// there's no ticket to show -- just the echo of the question and the
// decision, so it doesn't look like the card simply vanished on its own.
export function DeclinedNotice({ declined }: { declined: DeclinedConfirmation }) {
  const reason = REASON_LABEL[declined.reason] ?? 'hablar con un asesor'

  return (
    <p
      className="text-muted-foreground bg-card mx-auto flex max-w-2xl items-center gap-2 rounded-lg border px-4 py-2.5 text-sm"
      role="status"
    >
      <CircleX className="size-4 shrink-0" aria-hidden="true" />
      ¿Te derivamos para {reason}? · Ahora no
    </p>
  )
}
