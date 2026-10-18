import { describe, expect, it } from 'vitest'

import type { ServerEvent } from '../../api/types'
import { type ChatState, chatReducer, initialChatState } from './reducer'

function apply(state: ChatState, ...events: ServerEvent[]): ChatState {
  return events.reduce((acc, event) => chatReducer(acc, { type: 'server', event }), state)
}

describe('chatReducer', () => {
  it('acumula los deltas en una sola burbuja del agente', () => {
    const state = apply(
      initialChatState,
      { type: 'message.delta', delta: 'Hola ' },
      { type: 'message.delta', delta: 'Diego' },
    )

    expect(state.messages).toHaveLength(1)
    expect(state.messages[0]?.content).toBe('Hola Diego')
    expect(state.messages[0]?.streaming).toBe(true)
  })

  it('cierra la burbuja y guarda las métricas al completar el turno', () => {
    const streamed = apply(initialChatState, { type: 'message.delta', delta: 'Hola' })
    const state = apply(streamed, {
      type: 'message.completed',
      message_id: 'evt-1',
      trace_id: 'trace-1',
      latency_ms: 340,
      tokens_in: 1200,
      tokens_out: 80,
      model: 'gemini-3.8-flash',
    })

    expect(state.messages[0]?.streaming).toBe(false)
    expect(state.messages[0]?.id).toBe('evt-1')
    expect(state.streaming).toBe(false)
    expect(state.metrics?.latency_ms).toBe(340)
    expect(state.metrics?.trace_id).toBe('trace-1')
  })

  it('no mezcla el mensaje del usuario con el del agente', () => {
    const sent = chatReducer(initialChatState, { type: 'user-sent', content: 'Busco un SUV' })
    const state = apply(sent, { type: 'message.delta', delta: 'Buena elección' })

    expect(state.messages.map((m) => m.role)).toEqual(['user', 'agent'])
    expect(state.messages[0]?.content).toBe('Busco un SUV')
  })

  it('marca la actividad de una tool como terminada', () => {
    const state = apply(
      initialChatState,
      { type: 'tool.started', name: 'save_lead' },
      { type: 'tool.finished', name: 'save_lead', status: 'ok', duration_ms: 12 },
    )

    expect(state.activity).toEqual([{ name: 'save_lead', done: true }])
  })

  it('limpia la actividad cuando el turno termina', () => {
    const state = apply(
      initialChatState,
      { type: 'tool.started', name: 'search_knowledge_base' },
      {
        type: 'message.completed',
        message_id: 'e',
        trace_id: 't',
        latency_ms: 1,
        tokens_in: 1,
        tokens_out: 1,
        model: null,
      },
    )

    expect(state.activity).toEqual([])
  })

  it('actualiza ficha y etapa con lead.updated', () => {
    const state = apply(initialChatState, {
      type: 'lead.updated',
      lead: { name: 'Diego', contact_consent: false },
      stage: 'DISCOVERY',
    })

    expect(state.lead?.name).toBe('Diego')
    expect(state.stage).toBe('DISCOVERY')
  })

  it('deja la confirmación pendiente y detiene el streaming', () => {
    const state = apply(initialChatState, {
      type: 'hitl.confirmation_required',
      confirmation_id: 'conf-1',
      reason: 'TEST_DRIVE',
      resumen: 'Quiere agendar un test drive',
      preferred_channel: 'WHATSAPP',
      urgency: null,
    })

    expect(state.pendingConfirmation?.confirmation_id).toBe('conf-1')
    expect(state.streaming).toBe(false)
  })

  it('reemplaza la confirmación por el handoff creado, colgado del último mensaje', () => {
    const asked = apply(
      chatReducer(initialChatState, { type: 'user-sent', content: 'quiero un test drive' }),
      {
        type: 'hitl.confirmation_required',
        confirmation_id: 'conf-1',
        reason: 'TEST_DRIVE',
        resumen: 'x',
        preferred_channel: null,
        urgency: null,
      },
    )
    const state = apply(asked, {
      type: 'handoff.created',
      handoff_id: 1,
      ticket: 'TICK-00001',
      reason: 'TEST_DRIVE',
      status: 'OPEN',
      ya_existia: false,
    })

    expect(state.pendingConfirmation).toBeNull()
    expect(state.messages.at(-1)?.decision).toEqual({
      kind: 'handoff',
      ticket: 'TICK-00001',
      ya_existia: false,
    })
  })

  it('al declinar, quita la confirmación pendiente y cuelga el eco del último mensaje', () => {
    const asked = apply(
      chatReducer(initialChatState, { type: 'user-sent', content: 'quiero un test drive' }),
      {
        type: 'hitl.confirmation_required',
        confirmation_id: 'conf-1',
        reason: 'TEST_DRIVE',
        resumen: 'x',
        preferred_channel: null,
        urgency: null,
      },
    )

    const state = chatReducer(asked, { type: 'confirmation-declined' })

    expect(state.pendingConfirmation).toBeNull()
    expect(state.messages.at(-1)?.decision).toEqual({ kind: 'declined', reason: 'TEST_DRIVE' })
  })

  it('un mensaje nuevo NO borra el eco de una decisión anterior', () => {
    const asked = apply(
      chatReducer(initialChatState, { type: 'user-sent', content: 'quiero un test drive' }),
      {
        type: 'hitl.confirmation_required',
        confirmation_id: 'conf-1',
        reason: 'TEST_DRIVE',
        resumen: 'x',
        preferred_channel: null,
        urgency: null,
      },
    )
    const declined = chatReducer(asked, { type: 'confirmation-declined' })

    // The real bug reported: continuing the conversation erased the echo
    // forever, even though the row with the decision was still on screen.
    const state = chatReducer(declined, { type: 'user-sent', content: 'otra cosa' })

    const declinedMessage = state.messages.find((message) => message.decision?.kind === 'declined')
    expect(declinedMessage?.decision).toEqual({ kind: 'declined', reason: 'TEST_DRIVE' })
  })

  it('expone el error y recuerda el último mensaje para reintentar', () => {
    const sent = chatReducer(initialChatState, { type: 'user-sent', content: 'hola' })
    const state = apply(sent, {
      type: 'error',
      code: 'UPSTREAM_UNAVAILABLE',
      message: 'No pudimos conectar con el asesor.',
      retryable: true,
    })

    expect(state.error?.retryable).toBe(true)
    expect(state.lastUserMessage).toBe('hola')
    expect(state.streaming).toBe(false)
  })

  it('descarta la burbuja a medio escribir si el turno falla', () => {
    const streaming = apply(initialChatState, { type: 'message.delta', delta: 'a medio' })
    const state = chatReducer(streaming, { type: 'turn-failed', message: 'se cayó' })

    expect(state.messages).toEqual([])
    expect(state.error?.message).toBe('se cayó')
  })

  it('ofrece reintentar al cargar una conversación que terminó sin respuesta', () => {
    const state = chatReducer(initialChatState, {
      type: 'load',
      messages: [
        { id: 'stored-0', role: 'user', content: 'hola', streaming: false },
        { id: 'stored-1', role: 'user', content: 'q tal?', streaming: false },
      ],
      lead: null,
      stage: 'NEW',
      unansweredMessage: 'q tal?',
    })

    expect(state.error?.retryable).toBe(true)
    expect(state.lastUserMessage).toBe('q tal?')
    // The message stays in the list exactly as it came from the backend: the
    // "needs retry" signal is separate, it doesn't replace the history.
    expect(state.messages).toHaveLength(2)
  })

  it('no muestra el aviso de reintento si el último mensaje ya tiene respuesta', () => {
    const state = chatReducer(initialChatState, {
      type: 'load',
      messages: [
        { id: 'stored-0', role: 'user', content: 'hola', streaming: false },
        { id: 'stored-1', role: 'agent', content: '¡Hola!', streaming: false },
      ],
      lead: null,
      stage: 'NEW',
      unansweredMessage: null,
    })

    expect(state.error).toBeNull()
    expect(state.lastUserMessage).toBeNull()
  })

  it('corrige el último mensaje en su propia burbuja al editarlo', () => {
    const loaded = chatReducer(initialChatState, {
      type: 'load',
      messages: [
        { id: 'stored-0', role: 'user', content: 'hola', streaming: false },
        { id: 'stored-1', role: 'user', content: 'q tal?', streaming: false },
      ],
      lead: null,
      stage: 'NEW',
      unansweredMessage: 'q tal?',
    })

    const state = chatReducer(loaded, {
      type: 'edit-last-message',
      content: 'q lindas son las camionetas no?',
    })

    // Same message (same id, same position), not a new one added.
    expect(state.messages).toHaveLength(2)
    expect(state.messages[1]).toMatchObject({
      id: 'stored-1',
      content: 'q lindas son las camionetas no?',
    })
    expect(state.lastUserMessage).toBe('q lindas son las camionetas no?')
    expect(state.error).toBeNull()
  })
})
