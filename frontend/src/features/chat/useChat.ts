import { useCallback, useEffect, useReducer, useRef, useState } from 'react'

import { StreamIdleTimeoutError, api, sendConfirmation, sendMessage } from '../../api/client'
import { navigate, sessionIdFromPath, sessionPath } from '../../lib/route'
import type { ModelOption, ServerEvent, SessionSummary } from '../../api/types'
import { type Message, chatReducer, initialChatState } from './reducer'

const GENERIC_ERROR = 'No pudimos conectar con el asesor. Reintenta en unos segundos.'
const TIMEOUT_ERROR = 'El asesor tardó demasiado en responder. Reintenta en unos segundos.'

// Eventos que cierran un turno de verdad. Si el stream termina sin haber
// emitido ninguno, la conexión se cortó a medias (crash del backend, red de
// Docker caída): no es un turno silencioso legítimo, es un fallo que hay que
// mostrar con un reintento en vez de dejar la interfaz colgada en "escribiendo".
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
  const [state, dispatch] = useReducer(chatReducer, initialChatState)
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  // La URL es la fuente de verdad de qué conversación se ve, no un estado
  // aparte: así "/" es siempre el borrador sin crear y "/c/:id" es siempre
  // navegable, se puede recargar o pegar en otra pestaña sin perder el lugar.
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
      // Preferencia accesoria: si el almacenamiento falla, solo no se recuerda.
    }
  }, [])

  const refreshSessions = useCallback(async () => {
    try {
      setSessions(await api.listSessions())
    } catch {
      // La lista es accesoria: si falla, el chat sigue usable.
    }
  }, [])

  // Separado de openSession() para que tanto un clic en la barra lateral como
  // cargar la app directamente en /c/:id (un link, un refresh, atrás/adelante
  // del navegador) puedan reusar la misma carga de mensajes y ficha.
  const loadSessionData = useCallback(async (id: string) => {
    const [messages, lead] = await Promise.all([api.listMessages(id), api.getLead(id)])
    const mapped = messages.map(
      (message, index): Message => ({
        id: `stored-${index}`,
        role: message.role === 'user' ? 'user' : 'agent',
        content: message.content,
        streaming: false,
        // Eco persistente de una confirmación HITL ya resuelta (spec 02): sin
        // esto, recargar una conversación con handoff perdía el aviso de
        // "derivado"/"ahora no" y el mensaje quedaba como uno más.
        ...(message.decision ? { decision: message.decision } : {}),
      }),
    )
    // Si la conversación termina en un mensaje del usuario, ese turno nunca
    // tuvo respuesta (el backend no persiste que un turno falló, solo el
    // intercambio en sí). Se reconstruye la señal de "hay que reintentar"
    // para que no quede ahí colgado sin ninguna explicación al recargar.
    const last = mapped.at(-1)
    dispatch({
      type: 'load',
      messages: mapped,
      lead: lead.lead,
      stage: lead.stage as never,
      unansweredMessage: last?.role === 'user' ? last.content : null,
    })
  }, [])

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
          dispatch({ type: 'turn-failed', message: GENERIC_ERROR })
        }
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') return
        const message = error instanceof StreamIdleTimeoutError ? TIMEOUT_ERROR : GENERIC_ERROR
        dispatch({ type: 'turn-failed', message })
      }
    },
    [dispatch],
  )

  // Se guarda la promesa en curso, no solo un booleano: varios clics antes
  // del primer re-render caían todos dentro de la ventana en la que un
  // estado `creating` todavía valía false, y cada uno creaba su propia
  // sesión. Devolver la misma promesa a todos los que llegan mientras ya hay
  // una creación en vuelo evita la duplicación sin ignorar el clic.
  const creatingSessionRef = useRef<Promise<string> | null>(null)
  const [creatingSession, setCreatingSession] = useState(false)

  // Crea la sesión en el backend. A propósito NO es lo que dispara el botón
  // "Nueva conversación": eso llevaría a crear una fila real (y vacía) por
  // cada clic, incluida cada vez que la página se recarga con el borrador
  // sin usar. Solo send() la llama, y solo cuando de verdad hay un primer
  // mensaje que enviar — así una conversación entra a la lista cuando existe
  // algo que mostrar en ella, no antes.
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

  // Lo que de verdad hace el botón "Nueva conversación": vuelve al borrador
  // sin tocar el backend. Solo si se escribe algo ahí se crea una sesión de
  // verdad (ver createSession). Es puramente local, así que no hay carrera
  // posible por clics repetidos: no queda nada en vuelo que deba compartirse.
  const startNewConversation = useCallback(() => {
    abortRef.current?.abort()
    setSessionId(null)
    dispatch({ type: 'reset' })
  }, [setSessionId])

  const send = useCallback(
    // Cómo reflejar el texto en la lista antes de mandarlo:
    //   'append'       mensaje nuevo de verdad -> se agrega una burbuja (por defecto)
    //   'silent'       reintento tal cual -> ya está en pantalla, no se toca
    //   'replace-last' reintento editado -> corrige la última burbuja en su lugar
    async (text: string, mode: 'append' | 'silent' | 'replace-last' = 'append') => {
      if (mode === 'append') dispatch({ type: 'user-sent', content: text })
      else if (mode === 'replace-last') dispatch({ type: 'edit-last-message', content: text })
      // Feedback inmediato, antes de crear la sesión: para el primer mensaje
      // de una conversación nueva ese POST es una espera de red de verdad, y
      // sin esto la burbuja del usuario y el "escribiendo" no aparecían
      // hasta que terminaba -- la pantalla se veía igual que el borrador
      // vacío. Si alguien recargaba pensando que no había pasado nada, el
      // turno quedaba cortado a medias (visto en vivo).
      dispatch({ type: 'turn-start' })

      let id: string
      try {
        id = sessionId ?? (await createSession())
      } catch {
        dispatch({ type: 'turn-failed', message: GENERIC_ERROR })
        return
      }

      const controller = new AbortController()
      abortRef.current = controller
      await consume(sendMessage(id, text, modelId, controller.signal))
      await refreshSessions()
    },
    [sessionId, modelId, createSession, consume, refreshSessions],
  )

  const answerConfirmation = useCallback(
    async (approved: boolean) => {
      const pending = state.pendingConfirmation
      if (!sessionId || !pending) return

      if (!approved) {
        // Cancelar no crea nada (spec 03 §3): a diferencia de aprobar, donde
        // el aviso de ticket llega con el evento handoff.created, no hay
        // ningún evento de servidor que quite la tarjeta -- se quita de
        // inmediato en vez de esperar a que termine el turno reanudado.
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

  // Cuenta las veces que se mandó feedback con éxito: el panel dev la usa
  // como disparador para recargar su lista sola, en vez de necesitar F5.
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

  // Reintentar con el texto corregido: la burbuja se edita en su propio
  // lugar (reducer 'edit-last-message'), no se agrega una nueva.
  const editAndResend = useCallback(
    async (text: string) => {
      await send(text, 'replace-last')
    },
    [send],
  )

  // Vuelve a leer la URL al usar atrás/adelante del navegador: pushState (en
  // navigate(), lib/route.ts) no dispara 'popstate' por sí solo, pero un
  // cambio real de historial sí, y es la única forma en que la URL cambia
  // sin pasar por nuestros propios setSessionId/startNewConversation.
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

    // Si se entra directo a /c/:id (un link, un refresh, una pestaña nueva),
    // se carga esa conversación en vez de arrancar en el borrador vacío.
    if (sessionId) {
      loadSessionData(sessionId).catch(() => {
        // No existe o no es de este usuario: no tiene sentido dejar la URL
        // apuntando a algo que nunca va a cargar.
        setSessionId(null)
        dispatch({ type: 'reset' })
      })
    }

    void api
      .listModels()
      .then((available) => {
        setModels(available)
        // Si el modelo recordado ya no está en el catálogo (o dejó de estar
        // configurado), se cae al que el backend marca por defecto.
        setModelIdState((current) => {
          const usable = available.find((m) => m.id === current && m.available)
          return usable?.id ?? available.find((m) => m.is_default)?.id ?? null
        })
      })
      .catch(() => setModels([]))

    return () => abortRef.current?.abort()
    // Solo debe correr al montar: sessionId aquí es el de la URL inicial, no
    // algo a lo que este efecto deba reaccionar en cada cambio.
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
