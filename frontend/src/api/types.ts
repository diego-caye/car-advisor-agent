import type { components } from './schema'

export type LeadDto = components['schemas']['LeadDto']
export type LeadResponse = components['schemas']['LeadResponse']
export type SessionSummary = components['schemas']['SessionSummary']
export type MessageDto = components['schemas']['MessageDto']

export type Etapa =
  | 'NUEVO'
  | 'DESCUBRIMIENTO'
  | 'INTERES_CONCRETO'
  | 'DERIVACION_PENDIENTE'
  | 'DERIVADO'

export type ToolName = 'guardar_lead' | 'solicitar_contacto_humano' | 'search_knowledge_base'

export type ModelOption = components['schemas']['ModelOption']
export type FeedbackDto = components['schemas']['FeedbackDto']

/**
 * SSE events from specs/02-api-contract.md §2. They don't come from the
 * OpenAPI spec because the stream isn't described there; this type is the
 * contract with the backend.
 */
export type ServerEvent =
  | { type: 'message.delta'; delta: string }
  | {
      type: 'message.completed'
      message_id: string
      trace_id: string
      latency_ms: number
      tokens_in: number
      tokens_out: number
      model: string | null
    }
  | { type: 'tool.started'; name: string }
  | { type: 'tool.finished'; name: string; status: string; duration_ms: number }
  | { type: 'lead.updated'; lead: LeadDto | null; etapa: Etapa }
  | {
      type: 'hitl.confirmation_required'
      confirmation_id: string
      motivo: string
      resumen: string
      canal_preferido: string | null
      urgencia: string | null
    }
  | {
      type: 'handoff.created'
      handoff_id: number
      ticket: string
      motivo: string
      status: string
      ya_existia: boolean
    }
  | { type: 'guardrail.triggered'; layer: string; category: string }
  | { type: 'error'; code: string; message: string; retryable: boolean }

export type TurnMetrics = {
  latency_ms: number
  tokens_in: number
  tokens_out: number
  model: string | null
  trace_id: string
}
