import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { StreamIdleTimeoutError, api, sendConfirmation, sendMessage } from '../../api/client'
import { navigate, sessionIdFromPath, sessionPath } from '../../lib/route'
import type { ModelOption, ServerEvent, SessionSummary } from '../../api/types'
import { type Message, chatReducer, initialChatState } from './reducer'

// Events that actually close a turn. If the stream ends without having
// emitted any of these, the connection dropped halfway (backend crash,
// Docker network down): it isn't a legitimate silent turn, it's a failure
// that needs to be shown with a retry instead of leaving the UI stuck on "typing".
const TERMINAL_EVENTS: ReadonlySet<ServerEvent['type']> = new Set([
  'message.completed',
  'error',
  'hitl.confirmation_required',
  'handoff.created',
])

const MODEL_KEY = 'asesor.model_id'

function readStoredModel(): string | null {
  try {
    return localStorage.getItem(MODEL_KEY)
  } catch {
    return null
  }
}

export function useChat() {
  const { t } = useTranslation()
  const [state, dispatch] = useReducer(chatReducer, initialChatState)
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  // The URL is the source of truth for which conversation is shown, not a
  // separate piece of state: this way "/" is always the uncreated draft and
  // "/c/:id" is always navigable, can be reloaded or pasted into another tab
  // without losing your place.
  const [sessionId, setSessionIdState] = useState<string | null>(() =>
    sessionIdFromPath(window.location.pathname),
  )
  const [models, setModels] = useState<ModelOption[]>([])
  const [modelId, setModelIdState] = useState<string | null>(readStoredModel)
  const abortRef = useRef<AbortController | null>(null)

  const setSessionId = useCallback((id: string | null) => {
    setSessionIdState(id)
    navigate(id ? sessionPath(id) : '/')
  }, [])

  const setModelId = useCallback((id: string) => {
    setModelIdState(id)
    try {
      localStorage.setItem(MODEL_KEY, id)
    } catch {
      // Non-essential preference: if storage fails, it just isn't remembered.
    }
  }, [])

  const refreshSessions = useCallback(async () => {
    try {
      setSessions(await api.listSessions())
    } catch {
      // The list is non-essential: if it fails, chat is still usable.
    }
  }, [])

  // Separate from openSession() so that both a click on the sidebar and
  // loading the app directly at /c/:id (a link, a refresh, browser
  // back/forward) can reuse the same message-and-lead loading logic.
  const loadSessionData = useCallback(async (id: string) => {
    const [messages, lead] = await Promise.all([api.listMessages(id), api.getLead(id)])
    const mapped = messages.map(
      (message, index): Message => ({
        id: `stored-${index}`,
        role: message.role === 'user' ? 'user' : 'agent',
        content: message.content,
        streaming: false,
        // Persistent echo of an already-resolved HITL confirmation (spec 02):
        // without this, reloading a conversation with a handoff lost the
        // "handed off"/"not now" notice and the message ended up looking like any other.
        ...(message.decision ? { decision: message.decision } : {}),
      }),
    )
    // If the conversation ends on a user message, that turn never got a
    // response (the backend doesn't persist that a turn failed, only the
    // exchange itself). The "needs retry" signal is reconstructed so it
    // doesn't sit there with no explanation after reloading.
    const last = mapped.at(-1)
    dispatch({
      type: 'load',
      messages: mapped,
      lead: lead.lead,
      stage: lead.stage as never,
      unansweredMessage: last?.role === 'user' ? last.content : null,
      unansweredError: t('errors.unanswered'),
    })
  }, [t])

  const consume = useCallback(
    async (events: AsyncGenerator<ServerEvent>) => {
      dispatch({ type: 'turn-start' })
      let sawTerminalEvent = false
      try {
        for await (const event of events) {
          dispatch({ type: 'server', event })
          if (TERMINAL_EVENTS.has(event.type)) sawTerminalEvent = true
        }
        if (!sawTerminalEvent) {
          dispatch({ type: 'turn-failed', message: t('errors.generic') })
        }
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') return
        const message =
          error instanceof StreamIdleTimeoutError ? t('errors.timeout') : t('errors.generic')
        dispatch({ type: 'turn-failed', message })
      }
    },
    [dispatch, t],
  )

  // The in-flight promise is stored, not just a boolean: several clicks
  // before the first re-render all fell within the window where a
  // `creating` state was still false, and each one created its own session.
  // Returning the same promise to everyone who arrives while a creation is
  // already in flight avoids the duplication without ignoring the click.
  const creatingSessionRef = useRef<Promise<string> | null>(null)
  const [creatingSession, setCreatingSession] = useState(false)

  // Creates the session in the backend. On purpose this is NOT what the
  // "New conversation" button triggers: that would lead to creating a real
  // (and empty) row on every click, including every time the page is
  // reloaded with the draft unused. Only send() calls it, and only when
  // there's actually a first message to send — this way a conversation
  // enters the list once there's something to show in it, not before.
  const createSession = useCallback(async () => {
    if (creatingSessionRef.current) return creatingSessionRef.current

    const promise = (async () => {
      setCreatingSession(true)
      try {
        const { session_id } = await api.createSession()
        setSessionId(session_id)
        await refreshSessions()
        return session_id
      } finally {
        creatingSessionRef.current = null
        setCreatingSession(false)
      }
    })()

    creatingSessionRef.current = promise
    return promise
  }, [refreshSessions, setSessionId])

  const openSession = useCallback(
    async (id: string) => {
      abortRef.current?.abort()
      setSessionId(id)
      await loadSessionData(id)
    },
    [setSessionId, loadSessionData],
  )

  // What the "New conversation" button actually does: goes back to the
  // draft without touching the backend. Only if something is typed there
  // does a real session get created (see createSession). It's purely local,
  // so there's no possible race from repeated clicks: nothing stays in
  // flight that would need to be shared.
  const startNewConversation = useCallback(() => {
    abortRef.current?.abort()
    setSessionId(null)
    dispatch({ type: 'reset' })
  }, [setSessionId])

  const send = useCallback(
    // How to reflect the text in the list before sending it:
    //   'append'       a genuinely new message -> a bubble is added (default)
    //   'silent'       retry as-is -> already on screen, left untouched
    //   'replace-last' edited retry -> corrects the last bubble in place
    async (text: string, mode: 'append' | 'silent' | 'replace-last' = 'append') => {
      if (mode === 'append') dispatch({ type: 'user-sent', content: text })
      else if (mode === 'replace-last') dispatch({ type: 'edit-last-message', content: text })
      // Immediate feedback, before creating the session: for the first
      // message of a new conversation that POST is a real network wait, and
      // without this the user's bubble and the "typing" indicator didn't
      // appear until it finished -- the screen looked just like the empty
      // draft. If someone reloaded thinking nothing had happened, the turn
      // was left cut off halfway (seen live).
      dispatch({ type: 'turn-start' })

      let id: string
      try {
        id = sessionId ?? (await createSession())
      } catch {
        dispatch({ type: 'turn-failed', message: t('errors.generic') })
        return
      }

      const controller = new AbortController()
      abortRef.current = controller
      await consume(sendMessage(id, text, modelId, controller.signal))
      await refreshSessions()
    },
    [sessionId, modelId, createSession, consume, refreshSessions, t],
  )

  const answerConfirmation = useCallback(
    async (approved: boolean) => {
      const pending = state.pendingConfirmation
      if (!sessionId || !pending) return

      if (!approved) {
        // Declining doesn't create anything (spec 03 §3): unlike approving,
        // where the ticket notice arrives with the handoff.created event,
        // there's no server event that removes the card -- it's removed
        // immediately instead of waiting for the resumed turn to finish.
        dispatch({ type: 'confirmation-declined' })
      }

      const controller = new AbortController()
      abortRef.current = controller
      await consume(
        sendConfirmation(sessionId, pending.confirmation_id, approved, modelId, controller.signal),
      )
      await refreshSessions()
    },
    [sessionId, state.pendingConfirmation, modelId, consume, refreshSessions],
  )

  // Counts how many times feedback was sent successfully: the dev panel uses
  // it as a trigger to reload its own list, instead of needing an F5.
  const [feedbackVersion, setFeedbackVersion] = useState(0)

  const sendFeedback = useCallback(
    async (traceId: string, score: 1 | -1, message: string) => {
      if (!sessionId) return
      await api.sendFeedback(sessionId, traceId, score, message)
      setFeedbackVersion((version) => version + 1)
    },
    [sessionId],
  )

  const removeSession = useCallback(
    async (id: string) => {
      await api.deleteSession(id)

      if (id === sessionId) {
        abortRef.current?.abort()
        setSessionId(null)
        dispatch({ type: 'reset' })
      }

      await refreshSessions()
    },
    [sessionId, refreshSessions, setSessionId],
  )

  const retry = useCallback(async () => {
    if (state.lastUserMessage) await send(state.lastUserMessage, 'silent')
  }, [state.lastUserMessage, send])

  // Retry with the corrected text: the bubble is edited in place (reducer
  // 'edit-last-message'), a new one isn't added.
  const editAndResend = useCallback(
    async (text: string) => {
      await send(text, 'replace-last')
    },
    [send],
  )

  // Re-reads the URL when using the browser's back/forward: pushState (in
  // navigate(), lib/route.ts) doesn't fire 'popstate' on its own, but a real
  // history change does, and that's the only way the URL changes without
  // going through our own setSessionId/startNewConversation.
  useEffect(() => {
    function onPopState() {
      const id = sessionIdFromPath(window.location.pathname)
      setSessionIdState(id)
      if (id) {
        loadSessionData(id).catch(() => {
          navigate('/')
          setSessionIdState(null)
          dispatch({ type: 'reset' })
        })
      } else {
        dispatch({ type: 'reset' })
      }
    }

    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [loadSessionData])

  useEffect(() => {
    void refreshSessions()

    // If entering directly at /c/:id (a link, a refresh, a new tab), that
    // conversation is loaded instead of starting on the empty draft.
    if (sessionId) {
      loadSessionData(sessionId).catch(() => {
        // Doesn't exist or doesn't belong to this user: no point leaving the
        // URL pointing at something that will never load.
        setSessionId(null)
        dispatch({ type: 'reset' })
      })
    }

    void api
      .listModels()
      .then((available) => {
        setModels(available)
        // If the remembered model is no longer in the catalog (or stopped
        // being configured), it falls back to whichever the backend marks as default.
        setModelIdState((current) => {
          const usable = available.find((m) => m.id === current && m.available)
          return usable?.id ?? available.find((m) => m.is_default)?.id ?? null
        })
      })
      .catch(() => setModels([]))

    return () => abortRef.current?.abort()
    // Should only run on mount: sessionId here is the one from the initial
    // URL, not something this effect should react to on every change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshSessions])

  return {
    state,
    sessions,
    sessionId,
    creatingSession,
    models,
    modelId,
    setModelId,
    send,
    retry,
    editAndResend,
    startNewConversation,
    openSession,
    removeSession,
    answerConfirmation,
    sendFeedback,
    feedbackVersion,
  }
}
