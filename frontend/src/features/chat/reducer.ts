import type { Etapa, LeadDto, ServerEvent, TurnMetrics } from '../../api/types'

export type Handoff = { ticket: string; ya_existia: boolean }

// Echo of the confirmation card, accepted or declined: unlike approving
// (where handoff.created tells the story with the ticket), declining
// doesn't create anything on the backend side, so without this no trace
// would remain of what was asked or what was answered.
export type DeclinedConfirmation = { motivo: string }

// Goes INSIDE the message it belongs to (the one that triggered the
// handoff), not in a separate field of the global state: a separate field
// used to get cleared on every new user message (to avoid carrying the echo
// of an old topic into the next turn), but that also erased the echo
// forever as soon as the conversation continued, even though the row was
// still right there in its own bubble — reported live. Attached to the
// message, it survives only because the message itself is never deleted.
export type MessageDecision =
  | ({ kind: 'handoff' } & Handoff)
  | ({ kind: 'declined' } & DeclinedConfirmation)

export type Message = {
  id: string
  role: 'user' | 'agent'
  content: string
  streaming: boolean
  decision?: MessageDecision
}

export type Activity = { name: string; done: boolean }

export type Confirmation = {
  confirmation_id: string
  motivo: string
  resumen: string
  canal_preferido: string | null
}

export type ChatState = {
  messages: Message[]
  activity: Activity[]
  pendingConfirmation: Confirmation | null
  lead: LeadDto | null
  etapa: Etapa
  metrics: TurnMetrics | null
  streaming: boolean
  error: { message: string; retryable: boolean } | null
  lastUserMessage: string | null
}

export const initialChatState: ChatState = {
  messages: [],
  activity: [],
  pendingConfirmation: null,
  lead: null,
  etapa: 'NUEVO',
  metrics: null,
  streaming: false,
  error: null,
  lastUserMessage: null,
}

// The backend doesn't persist that a turn failed, only the exchange itself:
// if the last saved message is the user's, there was no response (the model
// failed, the connection dropped halfway, whatever). Without this, reloading
// such a conversation leaves the message hanging there with no hint that it
// can be retried — it ends up looking the same as a live failure.
const UNANSWERED_ERROR = 'Esta conversación se quedó sin respuesta. Puedes reintentar.'

export type ChatAction =
  | { type: 'reset' }
  | {
      type: 'load'
      messages: Message[]
      lead: LeadDto | null
      etapa: Etapa
      unansweredMessage?: string | null
    }
  | { type: 'user-sent'; content: string }
  // Corrects the last message's text in place (the same bubble), instead of
  // adding a new one: this is what "Edit" triggers on a message that was
  // left without a response.
  | { type: 'edit-last-message'; content: string }
  | { type: 'turn-start' }
  | { type: 'server'; event: ServerEvent }
  | { type: 'turn-failed'; message: string }
  // Declining doesn't create anything (spec 03 §3): unlike approving, where
  // the handoff.created event itself removes the card, declining has no
  // server event that "announces" it's already resolved -- it has to be
  // removed by hand as soon as the user decides, without waiting for the backend.
  | { type: 'confirmation-declined' }

const AGENT_DRAFT_ID = 'agent-draft'

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case 'reset':
      return initialChatState

    case 'load':
      return {
        ...initialChatState,
        messages: action.messages,
        lead: action.lead,
        etapa: action.etapa,
        ...(action.unansweredMessage
          ? {
              lastUserMessage: action.unansweredMessage,
              error: { message: UNANSWERED_ERROR, retryable: true },
            }
          : {}),
      }

    case 'user-sent':
      return {
        ...state,
        error: null,
        lastUserMessage: action.content,
        messages: [
          ...state.messages,
          {
            id: `user-${state.messages.length}`,
            role: 'user',
            content: action.content,
            streaming: false,
          },
        ],
      }

    case 'edit-last-message':
      return {
        ...state,
        error: null,
        lastUserMessage: action.content,
        messages: state.messages.map((message, index) =>
          index === state.messages.length - 1 ? { ...message, content: action.content } : message,
        ),
      }

    case 'turn-start':
      return { ...state, streaming: true, error: null, activity: [] }

    case 'turn-failed':
      return {
        ...state,
        streaming: false,
        activity: [],
        error: { message: action.message, retryable: true },
        messages: state.messages.filter((message) => message.id !== AGENT_DRAFT_ID),
      }

    case 'server':
      return applyServerEvent(state, action.event)

    case 'confirmation-declined': {
      const motivo = state.pendingConfirmation?.motivo
      const cleared = clearConfirmation(state)
      return motivo
        ? { ...cleared, messages: attachDecision(cleared.messages, { kind: 'declined', motivo }) }
        : cleared
    }
  }
}

function applyServerEvent(state: ChatState, event: ServerEvent): ChatState {
  switch (event.type) {
    case 'message.delta':
      return { ...state, messages: appendDelta(state.messages, event.delta) }

    case 'message.completed':
      return {
        ...state,
        streaming: false,
        activity: [],
        messages: state.messages.map((message) =>
          message.id === AGENT_DRAFT_ID
            ? { ...message, id: event.message_id || message.id, streaming: false }
            : message,
        ),
        metrics: {
          latency_ms: event.latency_ms,
          tokens_in: event.tokens_in,
          tokens_out: event.tokens_out,
          model: event.model,
          trace_id: event.trace_id,
        },
      }

    case 'tool.started':
      return { ...state, activity: [...state.activity, { name: event.name, done: false }] }

    case 'tool.finished':
      return {
        ...state,
        activity: state.activity.map((item) =>
          item.name === event.name && !item.done ? { ...item, done: true } : item,
        ),
      }

    case 'lead.updated':
      return { ...state, lead: event.lead, etapa: event.etapa }

    case 'hitl.confirmation_required':
      return {
        ...state,
        streaming: false,
        activity: [],
        pendingConfirmation: {
          confirmation_id: event.confirmation_id,
          motivo: event.motivo,
          resumen: event.resumen,
          canal_preferido: event.canal_preferido,
        },
      }

    case 'handoff.created':
      return {
        ...state,
        pendingConfirmation: null,
        messages: attachDecision(state.messages, {
          kind: 'handoff',
          ticket: event.ticket,
          ya_existia: event.ya_existia,
        }),
      }

    case 'guardrail.triggered':
      return state

    case 'error':
      return {
        ...state,
        streaming: false,
        activity: [],
        error: { message: event.message, retryable: event.retryable },
      }
  }
}

function appendDelta(messages: Message[], delta: string): Message[] {
  const last = messages[messages.length - 1]

  if (last && last.id === AGENT_DRAFT_ID) {
    return [...messages.slice(0, -1), { ...last, content: last.content + delta }]
  }

  return [
    ...messages,
    { id: AGENT_DRAFT_ID, role: 'agent', content: delta, streaming: true },
  ]
}

export function clearConfirmation(state: ChatState): ChatState {
  return { ...state, pendingConfirmation: null }
}

// The message the decision gets attached to is the last one in the
// conversation at that moment, whether the agent's or the user's: sometimes
// the model calls the handoff tool without prior text, so the last message
// on screen can be the user's own.
function attachDecision(messages: Message[], decision: MessageDecision): Message[] {
  if (messages.length === 0) return messages
  return messages.map((message, index) =>
    index === messages.length - 1 ? { ...message, decision } : message,
  )
}
