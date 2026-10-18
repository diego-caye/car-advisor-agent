import { afterEach, describe, expect, it, vi } from 'vitest'

import { StreamIdleTimeoutError, streamEvents } from './client'

/** A stream that never sends anything and never closes: simulates a hung connection. */
function stalledBody(): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start() {
      // Intentionally empty.
    },
  })
}

describe('streamEvents · timeout de inactividad', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('corta la conexión si no llega ni un byte en el plazo de espera', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, body: stalledBody() } as Response),
    )

    const events = streamEvents(
      '/api/v1/chat/stream',
      { session_id: 's1', message: 'hola' },
      new AbortController().signal,
      20, // plazo corto y timers reales: nada de fake timers para esto
    )

    await expect(events.next()).rejects.toBeInstanceOf(StreamIdleTimeoutError)
  })

  it('no corta la conexión si llegan bytes antes del plazo', async () => {
    const encoder = new TextEncoder()
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('event: message.delta\ndata: {"delta":"hola"}\n\n'))
      },
    })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, body } as Response))

    const events = streamEvents(
      '/api/v1/chat/stream',
      { session_id: 's1', message: 'hola' },
      new AbortController().signal,
      2000,
    )

    await expect(events.next()).resolves.toEqual({
      done: false,
      value: { type: 'message.delta', delta: 'hola' },
    })
  })
})
