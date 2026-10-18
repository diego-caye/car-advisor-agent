import { type KeyboardEvent, useEffect, useRef, useState } from 'react'
import { Pencil, RotateCcw, ThumbsDown, ThumbsUp } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'

import { DeclinedNotice, HandoffNotice } from '../hitl/ConfirmationCard'
import type { Activity, Message } from './reducer'
import { toolActivityLabel } from './labels'

type Props = {
  messages: Message[]
  activity: Activity[]
  streaming: boolean
  // Retry is offered when the last turn didn't get a response, whether from
  // a live failure or because an old conversation was loaded in that state.
  retryable: boolean
  onRetry: () => void
  onEdit: (text: string) => void
  // The "local model is slow" notice doesn't make sense with Gemini: there
  // the delay is the API's, not loading a model onto this machine's GPU.
  isLocalModel: boolean
  // trace_id of the last completed turn (spec 08 §4): without it there's no
  // trace to attach the score to in Langfuse, so feedback isn't offered.
  traceId: string | null
  onFeedback: (traceId: string, score: 1 | -1, message: string) => void
}

export function MessageList({
  messages,
  activity,
  streaming,
  retryable,
  onRetry,
  onEdit,
  isLocalModel,
  traceId,
  onFeedback,
}: Props) {
  const { t } = useTranslation()
  const endRef = useRef<HTMLDivElement>(null)
  const lastMessage = messages.at(-1)

  // The text arrives as a single event already filtered by L4, so between
  // sending and the response there's no bubble to show. Without this
  // indicator the UI looks frozen, and with a cold local model that's tens
  // of seconds.
  const pendingReply = streaming && lastMessage?.role !== 'agent'

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' })
  }, [messages, activity, streaming])

  return (
    <div
      className="flex-1 overflow-y-auto px-4 py-6 sm:px-8"
      aria-live="polite"
      aria-label={t('messageList.ariaLabel')}
    >
      <div className="mx-auto flex max-w-2xl flex-col gap-3">
        {messages.map((message) => {
          const isLastMessage = message.id === lastMessage?.id
          const isLastAgentMessage = message.role === 'agent' && isLastMessage
          return (
            <div key={message.id} className="flex flex-col gap-1.5">
              <Bubble
                message={message}
                // Only the last message can need a retry: it's the only one
                // left without a response. One in the middle already has it.
                showRetry={retryable && isLastMessage}
                retryDisabled={streaming}
                onRetry={onRetry}
                onEdit={onEdit}
                // Same "it's the last one" criterion: only the most recent
                // response makes sense to rate, not one in the middle of the conversation.
                showFeedback={!streaming && isLastAgentMessage && Boolean(traceId)}
                onFeedback={(score) => traceId && onFeedback(traceId, score, message.content)}
              />
              {/* The echo lives attached to the message itself (reducer), not
                  a separate field of the state: this way it survives
                  subsequent messages instead of being cleared as soon as
                  the conversation continues. */}
              {message.decision?.kind === 'handoff' && (
                <HandoffNotice handoff={message.decision} />
              )}
              {message.decision?.kind === 'declined' && (
                <DeclinedNotice declined={message.decision} />
              )}
            </div>
          )
        })}

        {activity
          .map((item, index) => ({ ...item, index }))
          .filter((item) => !item.done)
          .map((item) => (
            // The same tool can be called more than once in a turn (e.g.
            // save_lead twice): the name alone isn't a unique key.
            <ActivityChip key={`${item.name}-${item.index}`} name={item.name} />
          ))}

        {pendingReply && <TypingIndicator isLocalModel={isLocalModel} />}

        <div ref={endRef} />
      </div>
    </div>
  )
}

function Bubble({
  message,
  showRetry,
  retryDisabled,
  onRetry,
  onEdit,
  showFeedback,
  onFeedback,
}: {
  message: Message
  showRetry: boolean
  retryDisabled: boolean
  onRetry: () => void
  onEdit: (text: string) => void
  showFeedback: boolean
  onFeedback: (score: 1 | -1) => void
}) {
  const { t } = useTranslation()
  const isUser = message.role === 'user'
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(message.content)
  // Local: once a turn is rated you can't change your mind, and the state
  // doesn't need to survive a refresh (it's not information the user would
  // expect to get back, unlike the message itself).
  const [feedbackSent, setFeedbackSent] = useState<1 | -1 | null>(null)

  function sendFeedback(score: 1 | -1) {
    if (feedbackSent !== null) return
    setFeedbackSent(score)
    onFeedback(score)
  }

  function startEdit() {
    setDraft(message.content)
    setEditing(true)
  }

  function confirmEdit() {
    const trimmed = draft.trim()
    if (!trimmed) return
    setEditing(false)
    onEdit(trimmed)
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      confirmEdit()
    } else if (event.key === 'Escape') {
      setEditing(false)
    }
  }

  // Editing happens right in the message's own div: the bubble turns into
  // an editable field in place, instead of sending the text to the main
  // box below. On confirm, this same bubble ends up with the corrected text
  // (reducer 'edit-last-message') — a separate one isn't added.
  if (editing) {
    return (
      <div className="flex flex-col items-end">
        <Textarea
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
          autoFocus
          rows={2}
          maxLength={2000}
          className="max-w-[92%] resize-none text-[15px] sm:max-w-[80%]"
        />
        <div className="mt-1 flex gap-1">
          <Button type="button" size="xs" onClick={confirmEdit} disabled={!draft.trim()}>
            {t('messageList.saveAndSend')}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="xs"
            onClick={() => setEditing(false)}
            className="text-muted-foreground hover:text-foreground"
          >
            {t('messageList.cancel')}
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className={isUser ? 'flex flex-col items-end' : 'flex flex-col items-start'}>
      <p
        className={[
          'max-w-[92%] px-4 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap sm:max-w-[80%]',
          isUser
            ? 'rounded-[14px] rounded-br-[4px] bg-user-bubble'
            : 'rounded-[14px] rounded-bl-[4px] bg-card border',
          message.streaming ? 'caret' : '',
        ].join(' ')}
      >
        {message.content}
      </p>

      {/* Next to the specific message being resent, not a big, ambiguous
          button at the bottom of the screen that doesn't make clear what's
          being retried. */}
      {showRetry && (
        <div className="mt-1 flex gap-1">
          <Button
            type="button"
            variant="ghost"
            size="xs"
            onClick={onRetry}
            disabled={retryDisabled}
            className="text-muted-foreground hover:text-foreground"
          >
            <RotateCcw aria-hidden="true" />
            {t('messageList.retry')}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="xs"
            onClick={startEdit}
            disabled={retryDisabled}
            className="text-muted-foreground hover:text-foreground"
          >
            <Pencil aria-hidden="true" />
            {t('messageList.edit')}
          </Button>
        </div>
      )}

      {showFeedback && (
        <div className="mt-1 flex items-center gap-1">
          <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            onClick={() => sendFeedback(1)}
            disabled={feedbackSent !== null}
            aria-label={t('messageList.goodReply')}
            title={t('messageList.goodReply')}
            className={
              feedbackSent === 1
                ? 'text-ok'
                : 'text-muted-foreground hover:text-foreground disabled:opacity-100'
            }
          >
            <ThumbsUp aria-hidden="true" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            onClick={() => sendFeedback(-1)}
            disabled={feedbackSent !== null}
            aria-label={t('messageList.badReply')}
            title={t('messageList.badReply')}
            className={
              feedbackSent === -1
                ? 'text-destructive'
                : 'text-muted-foreground hover:text-foreground disabled:opacity-100'
            }
          >
            <ThumbsDown aria-hidden="true" />
          </Button>
          {feedbackSent !== null && (
            <span className="text-muted-foreground text-xs">{t('messageList.thanksForFeedback')}</span>
          )}
        </div>
      )}
    </div>
  )
}

const SLOW_REPLY_MS = 8000

function TypingIndicator({ isLocalModel }: { isLocalModel: boolean }) {
  const { t } = useTranslation()
  const [slow, setSlow] = useState(false)

  useEffect(() => {
    const timer = setTimeout(() => setSlow(true), SLOW_REPLY_MS)
    return () => clearTimeout(timer)
  }, [])

  return (
    <div
      className="flex flex-col items-start gap-1.5"
      role="status"
      aria-label={t('messageList.agentTyping')}
    >
      <span className="inline-flex items-center gap-1.5 rounded-[14px] rounded-bl-[4px] bg-card border px-4 py-3">
        <Dot delay="0ms" />
        <Dot delay="160ms" />
        <Dot delay="320ms" />
      </span>
      {slow && (
        <span className="px-1 text-xs text-muted-foreground">
          {/* "local model is slow" doesn't make sense with Gemini: there the
              delay is the API's (or a 429 retry), not loading a model onto
              this machine's GPU. It also doesn't claim it's "the first time"
              for the local case: there's no way to know that from here, and
              saying it on the model's fifth call, already warmed up, is more
              confusing than reassuring. */}
          {isLocalModel ? t('messageList.slowLocalModel') : t('messageList.slowReply')}
        </span>
      )}
    </div>
  )
}

function Dot({ delay }: { delay: string }) {
  return (
    <span
      // bg-muted-foreground, not bg-muted: in dark mode --muted and --card
      // are literally the same gray (#171717), so the dots ended up
      // invisible over the bubble — only the empty border was visible.
      className="size-1.5 animate-bounce rounded-full bg-muted-foreground"
      style={{ animationDelay: delay }}
      aria-hidden="true"
    />
  )
}

function ActivityChip({ name }: { name: string }) {
  const { t } = useTranslation()
  return (
    <div className="flex justify-start" role="status">
      <Badge variant="secondary" className="bg-accent-soft text-muted-foreground h-auto py-1.5">
        <span className="bg-primary size-1.5 animate-pulse rounded-full" aria-hidden="true" />
        {toolActivityLabel(t, name)}
      </Badge>
    </div>
  )
}
