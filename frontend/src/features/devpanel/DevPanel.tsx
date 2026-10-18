import { useEffect, useState } from 'react'
import { ThumbsDown, ThumbsUp, Trash2, X } from 'lucide-react'

import { api } from '../../api/client'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { Sidebar, SidebarContent, SidebarHeader } from '@/components/ui/sidebar'

import type { FeedbackDto, LeadDto, TurnMetrics } from '../../api/types'
import { LEAD_FIELDS, STAGE_LABEL } from '../chat/labels'

type Props = {
  lead: LeadDto | null
  stage: string
  metrics: TurnMetrics | null
  onClose: () => void
  onOpenSession: (sessionId: string) => void
  // Incremented every time feedback is sent successfully, from anywhere in
  // the app: triggers the list reload without needing an F5.
  feedbackVersion: number
}

const LANGFUSE_PROJECT = import.meta.env['VITE_LANGFUSE_PROJECT_ID'] as string | undefined
// Without this, a plan that doesn't live on the default cloud.langfuse.com
// (e.g. a HIPAA region with its own host) builds the link against the wrong
// host and gets stuck on "Loading..." forever (seen live).
const LANGFUSE_HOST =
  (import.meta.env['VITE_LANGFUSE_HOST'] as string | undefined) || 'https://cloud.langfuse.com'

export function DevPanel({ lead, stage, metrics, onClose, onOpenSession, feedbackVersion }: Props) {
  const record = (lead ?? {}) as Record<string, unknown>

  return (
    <Sidebar side="right" collapsible="offcanvas">
      <SidebarHeader className="flex-row items-center justify-between p-4 pb-0">
        <Label>Panel dev</Label>
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          onClick={onClose}
          aria-label="Ocultar panel dev"
          className="text-muted-foreground hover:text-foreground"
        >
          <X aria-hidden="true" />
        </Button>
      </SidebarHeader>

      <SidebarContent className="gap-4 p-4 pt-2">
        <Separator />

        <section>
          <Label>Etapa</Label>
          <Badge variant="secondary" className="mt-1.5">
            {STAGE_LABEL[stage] ?? stage}
          </Badge>
        </section>

        <section>
          <Label>Ficha del lead</Label>
          <dl className="mt-1.5 flex flex-col gap-1">
            {LEAD_FIELDS.map((field) => {
              const value = record[field.key]
              return (
                <div key={field.key} className="flex justify-between gap-2 text-xs">
                  <dt className="text-muted-foreground">{field.label}</dt>
                  <dd className={value ? 'text-foreground' : 'text-muted-foreground'}>
                    {typeof value === 'string' && value ? value : '—'}
                  </dd>
                </div>
              )
            })}
          </dl>
        </section>

        <section>
          <Label>Último turno</Label>
          {metrics ? (
            <dl className="mt-1.5 flex flex-col gap-1 text-xs">
              <Row label="Latencia" value={`${metrics.latency_ms} ms`} />
              <Row label="Tokens in" value={String(metrics.tokens_in)} />
              <Row label="Tokens out" value={String(metrics.tokens_out)} />
              <Row label="Modelo" value={metrics.model ?? '—'} />
            </dl>
          ) : (
            <p className="text-muted-foreground mt-1.5 text-xs">Sin turnos todavía.</p>
          )}

          {metrics && LANGFUSE_PROJECT && (
            <Button asChild variant="link" size="xs" className="mt-2 px-0">
              <a
                href={`${LANGFUSE_HOST}/project/${LANGFUSE_PROJECT}/traces/${metrics.trace_id}`}
                target="_blank"
                rel="noreferrer"
              >
                Ver traza en Langfuse
              </a>
            </Button>
          )}
        </section>

        <Separator />

        <FeedbackSection onOpenSession={onOpenSession} refreshKey={feedbackVersion} />
      </SidebarContent>
    </Sidebar>
  )
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-muted-foreground text-[11px] font-medium tracking-[0.04em] uppercase">
      {children}
    </h2>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="tabular">{value}</dd>
    </div>
  )
}

// No token or login: the project has no real auth model anywhere else
// (X-User-Id is a UUID the client itself sets), so gating just this
// wouldn't add real security, only friction for whoever evaluates the challenge.
function FeedbackSection({
  onOpenSession,
  refreshKey,
}: {
  onOpenSession: (sessionId: string) => void
  refreshKey: number
}) {
  const [entries, setEntries] = useState<FeedbackDto[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<number | null>(null)

  useEffect(() => {
    void load()
    // On mount (opening the panel) and every time refreshKey changes
    // (feedback was sent successfully) -- previously the new row only showed
    // up by reloading the whole tab.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey])

  async function load() {
    setLoading(true)
    setError(null)
    try {
      setEntries(await api.listFeedback())
    } catch {
      setError('No se pudo cargar el feedback.')
    } finally {
      setLoading(false)
    }
  }

  async function handleDelete(id: number) {
    setDeletingId(id)
    setError(null)
    try {
      await api.deleteFeedback(id)
      setEntries((prev) => prev?.filter((entry) => entry.id !== id) ?? null)
    } catch {
      setError('No se pudo borrar el feedback.')
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <section>
      <div className="flex items-center justify-between">
        <Label>Feedback</Label>
        <Button
          type="button"
          size="xs"
          variant="ghost"
          className="text-muted-foreground h-5 px-1.5 text-[11px]"
          onClick={() => void load()}
          disabled={loading}
        >
          Actualizar
        </Button>
      </div>

      {error && <p className="text-destructive mt-1 text-xs">{error}</p>}

      {!entries && !error && (
        <p className="text-muted-foreground mt-1.5 text-xs">Cargando…</p>
      )}

      {entries && entries.length === 0 && (
        <p className="text-muted-foreground mt-1.5 text-xs">Sin feedback todavía.</p>
      )}

      {entries && entries.length > 0 && (
        <ul className="mt-1.5 flex flex-col gap-1.5">
          {entries.map((entry) => (
            <li key={entry.id} className="group relative">
              <button
                type="button"
                onClick={() => onOpenSession(entry.session_id)}
                className="bg-card hover:bg-accent w-full rounded-md border px-2 py-1.5 pr-7 text-left"
              >
                <div className="flex items-center gap-1.5">
                  {entry.score === 1 ? (
                    <ThumbsUp className="text-ok size-3 shrink-0" aria-hidden="true" />
                  ) : (
                    <ThumbsDown className="text-destructive size-3 shrink-0" aria-hidden="true" />
                  )}
                  <span className="text-muted-foreground text-[10px] tabular">
                    {new Date(entry.created_at).toLocaleString()}
                  </span>
                </div>
                <p className="mt-0.5 line-clamp-2 text-xs">{entry.message}</p>
              </button>

              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    aria-label="Eliminar feedback"
                    title="Eliminar feedback"
                    disabled={deletingId === entry.id}
                    className="text-muted-foreground hover:text-destructive absolute top-1/2 right-1 -translate-y-1/2 opacity-0 group-hover:opacity-100"
                  >
                    <Trash2 aria-hidden="true" />
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>¿Eliminar este feedback?</AlertDialogTitle>
                    <AlertDialogDescription>
                      Se borra esta fila del panel de revisión. La conversación no se toca.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Cancelar</AlertDialogCancel>
                    <AlertDialogAction
                      variant="destructive"
                      onClick={() => void handleDelete(entry.id)}
                    >
                      Eliminar
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
