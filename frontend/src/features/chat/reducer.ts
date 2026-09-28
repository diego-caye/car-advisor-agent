import type { LeadDto, ServerEvent, Stage, TurnMetrics } from '../../api/types'

export type Handoff = { ticket: string; ya_existia: boolean }

// Eco de la tarjeta de confirmación, aceptada o declinada: a diferencia de
// aprobar (donde handoff.created cuenta la historia con el ticket), cancelar
// no crea nada del lado del backend, así que sin esto no queda ningún rastro
// de qué se preguntó ni qué se contestó.
export type DeclinedConfirmation = { reason: string }

// Va DENTRO del mensaje al que pertenece (el que disparó la derivación), no
// en un campo aparte del estado global: un campo aparte se limpiaba con
// cada mensaje nuevo del usuario (para no arrastrar el eco de un tema viejo
// al turno siguiente) pero eso también borraba el eco para siempre en
// cuanto se seguía conversando, aunque la fila siguiera ahí en la propia
// burbuja — reportado en vivo. Colgado del mensaje, sobrevive solo porque
// el mensaje mismo nunca se borra.
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
  reason: string
  resumen: string
  preferred_channel: string | null
}

export type ChatState = {
  messages: Message[]
  activity: Activity[]
  pendingConfirmation: Confirmation | null
  lead: LeadDto | null
  stage: Stage
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
  stage: 'NEW',
  metrics: null,
  streaming: false,
  error: null,
  lastUserMessage: null,
}

// El backend no persiste que un turno falló, solo el intercambio en sí: si el
// último mensaje guardado es del usuario, no hubo respuesta (el modelo falló,
// la conexión se cortó a medias, lo que sea). Sin esto, recargar una
// conversación así de deja el mensaje ahí colgado sin ninguna pista de que se
// puede reintentar — pasa a verse igual que en una falla en vivo.
const UNANSWERED_ERROR = 'Esta conversación se quedó sin respuesta. Puedes reintentar.'

export type ChatAction =
  | { type: 'reset' }
  | {
      type: 'load'
      messages: Message[]
      lead: LeadDto | null
      stage: Stage
      unansweredMessage?: string | null
    }
  | { type: 'user-sent'; content: string }
  // Corrige el texto del último mensaje en su propio lugar (la misma
  // burbuja), en vez de agregar uno nuevo: es lo que dispara "Editar" sobre
  // un mensaje que se quedó sin respuesta.
  | { type: 'edit-last-message'; content: string }
  | { type: 'turn-start' }
  | { type: 'server'; event: ServerEvent }
  | { type: 'turn-failed'; message: string }
  // Cancelar no crea nada (spec 03 §3): a diferencia de aprobar, donde la
  // tarjeta la quita el propio evento handoff.created, cancelar no tiene
  // ningún evento de servidor que "avise" que ya se resolvió -- hay que
  // quitarla a mano en cuanto el usuario decide, sin esperar al backend.
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
        stage: action.stage,
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
      const reason = state.pendingConfirmation?.reason
      const cleared = clearConfirmation(state)
      return reason
        ? { ...cleared, messages: attachDecision(cleared.messages, { kind: 'declined', reason }) }
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
      return { ...state, lead: event.lead, stage: event.stage }

    case 'hitl.confirmation_required':
      return {
        ...state,
        streaming: false,
        activity: [],
        pendingConfirmation: {
          confirmation_id: event.confirmation_id,
          reason: event.reason,
          resumen: event.resumen,
          preferred_channel: event.preferred_channel,
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

// El mensaje al que se cuelga la decisión es el último de la conversación en
// ese momento, sea del agente o del usuario: a veces el modelo llama la tool
// de derivación sin texto previo, así que el último mensaje en pantalla
// puede ser el del propio usuario.
function attachDecision(messages: Message[], decision: MessageDecision): Message[] {
  if (messages.length === 0) return messages
  return messages.map((message, index) =>
    index === messages.length - 1 ? { ...message, decision } : message,
  )
}
