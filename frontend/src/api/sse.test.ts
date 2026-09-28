import { describe, expect, it } from 'vitest'

import { createSseParser, toServerEvent } from './sse'

describe('createSseParser', () => {
  it('parsea un frame completo', () => {
    const parse = createSseParser()

    expect(parse('event: message.delta\ndata: {"delta":"hola"}\n\n')).toEqual([
      { event: 'message.delta', data: '{"delta":"hola"}' },
    ])
  })

  it('espera a que el frame esté completo si el chunk lo parte', () => {
    const parse = createSseParser()

    expect(parse('event: message.delta\ndata: {"del')).toEqual([])
    expect(parse('ta":"hola"}\n\n')).toEqual([
      { event: 'message.delta', data: '{"delta":"hola"}' },
    ])
  })

  it('devuelve varios frames de un mismo chunk', () => {
    const parse = createSseParser()

    const frames = parse(
      'event: tool.started\ndata: {"name":"save_lead"}\n\n' +
        'event: tool.finished\ndata: {"name":"save_lead"}\n\n',
    )

    expect(frames.map((f) => f.event)).toEqual(['tool.started', 'tool.finished'])
  })

  it('normaliza CRLF y descarta comentarios', () => {
    const parse = createSseParser()

    expect(parse(': keep-alive\r\nevent: error\r\ndata: {"code":"X"}\r\n\r\n')).toEqual([
      { event: 'error', data: '{"code":"X"}' },
    ])
  })

  it('ignora bloques sin nombre de evento', () => {
    const parse = createSseParser()

    expect(parse('data: {"suelto":true}\n\n')).toEqual([])
  })
})

describe('toServerEvent', () => {
  it('combina el nombre del evento con su payload', () => {
    expect(toServerEvent({ event: 'message.delta', data: '{"delta":"hola"}' })).toEqual({
      type: 'message.delta',
      delta: 'hola',
    })
  })

  it('devuelve null si el payload no es JSON válido', () => {
    expect(toServerEvent({ event: 'message.delta', data: '{roto' })).toBeNull()
  })
})
