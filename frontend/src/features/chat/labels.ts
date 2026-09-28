export const TOOL_ACTIVITY: Record<string, string> = {
  search_knowledge_base: 'Consultando la guía técnica…',
  save_lead: 'Guardando tus datos…',
  request_human_handoff: 'Preparando tu solicitud…',
}

export const REASON_LABEL: Record<string, string> = {
  TEST_DRIVE: 'agendar un test drive',
  FORMAL_QUOTE: 'una cotización formal',
  IMMEDIATE_PURCHASE: 'avanzar con la compra',
  DISSATISFACTION: 'atender un reclamo',
  OUT_OF_SCOPE: 'hablar con un especialista',
}

export const CHANNEL_LABEL: Record<string, string> = {
  WHATSAPP: 'WhatsApp',
  CALL: 'llamada',
  EMAIL: 'correo',
  CHAT: 'chat',
}

export const STAGE_LABEL: Record<string, string> = {
  NEW: 'Nuevo',
  DISCOVERY: 'Descubrimiento',
  CONCRETE_INTEREST: 'Interés concreto',
  HANDOFF_PENDING: 'Derivación pendiente',
  HANDED_OFF: 'Derivado',
}

export const LEAD_FIELDS: { key: string; label: string }[] = [
  { key: 'name', label: 'Nombre' },
  { key: 'primary_use', label: 'Uso' },
  { key: 'vehicle_type_interest', label: 'Carrocería' },
  { key: 'powertrain_interest', label: 'Motor' },
  { key: 'interest_level', label: 'Interés' },
  { key: 'preferred_channel', label: 'Canal' },
]
