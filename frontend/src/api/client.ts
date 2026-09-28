import { createSseParser, toServerEvent } from './sse'
import type {
  FeedbackDto,
  LeadResponse,
  MessageDto,
  ModelOption,
  ServerEvent,
  SessionSummary,
} from './types'

const USER_ID_KEY = 'asesor.user_id'

export function getUserId(): string {
  try {
    const stored = localStorage.getItem(USER_ID_KEY)
    if (stored) return stored
    const fresh = crypto.randomUUID()
    localStorage.setItem(USER_ID_KEY, fresh)
    return fresh
  } catch {
    // Private window or storage blocked: the session lives in memory only.
    return crypto.randomUUID()
  }
}

const userId = getUserId()

// The backend buffers the model's response and doesn't send anything over
// the wire until the turn finishes (spec 02 §4: L4 needs to see the full
// text). That means, for a turn without tools, the connection can stay
// completely silent for as long as generation takes — and with Gemini we've
// measured over 2 minutes for a single turn with provider retries. The
// deadline has to cover that with margin; what should actually cut the
// connection is a hung one (the model process died, Docker lost the
// network), not a slow turn.
const STREAM_IDLE_TIMEOUT_MS = 180_000

export class StreamIdleTimeoutError extends Error {
  constructor() {
    super('El asesor no respondió a tiempo.')
    this.name = 'StreamIdleTimeoutError'
  }
}

async function readWithIdleTimeout(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  timeoutMs: number,
): Promise<ReadableStreamReadResult<Uint8Array>> {
  let timer: ReturnType<typeof setTimeout> | undefined
  const read = reader.read()
  // If the timeout wins, we later cancel the reader and that pending read
  // can still end up rejecting: without this no-op, Node reports it as an
  // "unhandled rejection" even though the race's outcome has already settled.
  read.catch(() => {})
  try {
    return await Promise.race([
      read,
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new StreamIdleTimeoutError()), timeoutMs)
      }),
    ])
  } finally {
    clearTimeout(timer)
  }
}

function headers(): HeadersInit {
  return { 'Content-Type': 'application/json', 'X-User-Id': userId }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { ...init, headers: headers() })
  if (!response.ok) throw new Error(`${init?.method ?? 'GET'} ${path} → ${response.status}`)
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  createSession: () => request<{ session_id: string }>('/api/v1/sessions', { method: 'POST' }),
  listSessions: () => request<SessionSummary[]>('/api/v1/sessions'),
  listMessages: (sessionId: string) =>
    request<MessageDto[]>(`/api/v1/sessions/${sessionId}/messages`),
  getLead: (sessionId: string) => request<LeadResponse>(`/api/v1/sessions/${sessionId}/lead`),
  deleteSession: (sessionId: string) =>
    request<void>(`/api/v1/sessions/${sessionId}`, { method: 'DELETE' }),
  listModels: () => request<ModelOption[]>('/api/v1/models'),
  sendFeedback: (sessionId: string, traceId: string, score: 1 | -1, message: string) =>
    request<{ ok: boolean }>('/api/v1/feedback', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, trace_id: traceId, score, message }),
    }),
  // No token: the project has no real auth anywhere else (spec 02), so
  // gating just this endpoint wouldn't add real security, only friction.
  listFeedback: (limit = 50) => request<FeedbackDto[]>(`/api/v1/feedback?limit=${limit}`),
  deleteFeedback: (id: number) => request<void>(`/api/v1/feedback/${id}`, { method: 'DELETE' }),
}

// Exported only so the timeout test can pass a short deadline and use real
// timers, instead of waiting 3 minutes or dealing with fake timers racing
// inside a Promise.race.
export async function* streamEvents(
  path: string,
  body: unknown,
  signal: AbortSignal,
  idleTimeoutMs = STREAM_IDLE_TIMEOUT_MS,
): AsyncGenerator<ServerEvent> {
  const response = await fetch(path, {
    method: 'POST',
    headers: headers(),
    body: JSON.stringify(body),
    signal,
  })

  if (!response.ok || !response.body) {
    throw new Error(`POST ${path} → ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  const parse = createSseParser()

  try {
    while (true) {
      const { done, value } = await readWithIdleTimeout(reader, idleTimeoutMs)
      if (done) break

      for (const frame of parse(decoder.decode(value, { stream: true }))) {
        const event = toServerEvent(frame)
        if (event) yield event
      }
    }
  } catch (error) {
    // The timeout doesn't close the connection by itself: without this, the
    // hung request stays alive in the browser even after we've stopped reading it.
    await reader.cancel().catch(() => {})
    throw error
  }
}

export function sendMessage(
  sessionId: string,
  message: string,
  modelId: string | null,
  signal: AbortSignal,
): AsyncGenerator<ServerEvent> {
  return streamEvents(
    "/api/v1/chat/stream",
    { session_id: sessionId, message, model_id: modelId },
    signal,
  )
}

export function sendConfirmation(
  sessionId: string,
  confirmationId: string,
  approved: boolean,
  modelId: string | null,
  signal: AbortSignal,
): AsyncGenerator<ServerEvent> {
  return streamEvents(
    '/api/v1/chat/confirmations',
    { session_id: sessionId, confirmation_id: confirmationId, approved, model_id: modelId },
    signal,
  )
}
