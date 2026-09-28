import type { components } from './schema'

export type LeadDto = components['schemas']['LeadDto']
export type LeadResponse = components['schemas']['LeadResponse']
export type SessionSummary = components['schemas']['SessionSummary']
export type MessageDto = components['schemas']['MessageDto']

export type Stage =
  | 'NEW'
  | 'DISCOVERY'
  | 'CONCRETE_INTEREST'
  | 'HANDOFF_PENDING'
  | 'HANDED_OFF'

export type ToolName = 'save_lead' | 'request_human_handoff' | 'search_knowledge_base'

export type ModelOption = components['schemas']['ModelOption']
export type FeedbackDto = components['schemas']['FeedbackDto']

/**
 * Eventos SSE de specs/02-api-contract.md §2. No salen del OpenAPI porque el
 * stream no se describe ahí; este tipo es el contrato con el backend.
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
  | { type: 'lead.updated'; lead: LeadDto | null; stage: Stage }
  | {
      type: 'hitl.confirmation_required'
      confirmation_id: string
      reason: string
      resumen: string
      preferred_channel: string | null
      urgency: string | null
    }
  | {
      type: 'handoff.created'
      handoff_id: number
      ticket: string
      reason: string
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
