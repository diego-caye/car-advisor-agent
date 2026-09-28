import type { ServerEvent } from './types'

export type SseFrame = { event: string; data: string }

/**
 * Accumulates text and returns the complete frames. A network chunk can cut
 * a frame in half, so the incomplete part stays in the buffer.
 */
export function createSseParser(): (chunk: string) => SseFrame[] {
  let buffer = ''

  return (chunk: string): SseFrame[] => {
    buffer += chunk.replace(/\r\n/g, '\n')
    const frames: SseFrame[] = []

    let separator = buffer.indexOf('\n\n')
    while (separator !== -1) {
      const block = buffer.slice(0, separator)
      buffer = buffer.slice(separator + 2)

      const frame = parseFrame(block)
      if (frame) frames.push(frame)

      separator = buffer.indexOf('\n\n')
    }

    return frames
  }
}

function parseFrame(block: string): SseFrame | null {
  let event = ''
  const dataLines: string[] = []

  for (const line of block.split('\n')) {
    if (line.startsWith(':')) continue
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
  }

  if (!event) return null
  return { event, data: dataLines.join('\n') }
}

export function toServerEvent(frame: SseFrame): ServerEvent | null {
  let payload: unknown
  try {
    payload = frame.data ? JSON.parse(frame.data) : {}
  } catch {
    return null
  }

  if (typeof payload !== 'object' || payload === null) return null
  return { type: frame.event, ...payload } as ServerEvent
}
