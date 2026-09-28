import { useState, type CSSProperties } from 'react'
import { SlidersHorizontal, TriangleAlert } from 'lucide-react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar'
import { ThemeToggle } from '@/components/theme-toggle'

import { Composer } from './features/chat/Composer'
import { MessageList } from './features/chat/MessageList'
import { ModelSelect } from './features/chat/ModelSelect'
import { useChat } from './features/chat/useChat'
import { DevPanel } from './features/devpanel/DevPanel'
import { ConfirmationCard } from './features/hitl/ConfirmationCard'
import { Sidebar } from './features/sessions/Sidebar'

const DEV_PANEL_KEY = 'asesor.devpanel'

export default function App() {
  const {
    state,
    sessions,
    sessionId,
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
  } = useChat()
  const [showDevPanel, setShowDevPanel] = useState(readDevPanelPreference)

  function toggleDevPanel(next: boolean) {
    setShowDevPanel(next)
    try {
      localStorage.setItem(DEV_PANEL_KEY, String(next))
    } catch {
      // Preferencia accesoria: si el almacenamiento falla, solo no se recuerda.
    }
  }

  return (
    <SidebarProvider className="h-full">
      <Sidebar
        sessions={sessions}
        activeId={sessionId}
        onSelect={(id) => void openSession(id)}
        onCreate={startNewConversation}
        onDelete={(id) => void removeSession(id)}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b px-4 py-3 sm:px-8">
          <div className="flex items-center gap-2">
            <SidebarTrigger />
            <h1 className="text-[15px] font-semibold">
              Luis <span className="text-muted-foreground font-normal">· asesor automotriz</span>
            </h1>
          </div>
          <div className="flex items-center gap-2">
            <ModelSelect
              models={models}
              value={modelId}
              disabled={state.streaming}
              onChange={setModelId}
            />
            {!showDevPanel && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => toggleDevPanel(true)}
              >
                <SlidersHorizontal aria-hidden="true" />
                Panel dev
              </Button>
            )}
            <ThemeToggle />
          </div>
        </header>

        {state.messages.length === 0 && (
          <p className="text-muted-foreground mx-auto mt-10 max-w-md px-6 text-center text-sm">
            Cuéntale a Luis qué buscas: para qué usarás el auto, qué carrocería te llama o
            cualquier duda técnica. Te orienta sin presionarte.
          </p>
        )}

        <MessageList
          messages={state.messages}
          activity={state.activity}
          streaming={state.streaming}
          retryable={Boolean(state.error?.retryable && state.lastUserMessage)}
          onRetry={() => void retry()}
          onEdit={(text) => void editAndResend(text)}
          isLocalModel={models.find((model) => model.id === modelId)?.provider === 'ollama'}
          traceId={state.metrics?.trace_id ?? null}
          onFeedback={(traceId, score, message) => void sendFeedback(traceId, score, message)}
        />

        <div className="flex flex-col gap-3 border-t px-4 py-4 sm:px-8">
          {state.pendingConfirmation && (
            <ConfirmationCard
              confirmation={state.pendingConfirmation}
              busy={state.streaming}
              onAnswer={(approved) => void answerConfirmation(approved)}
            />
          )}

          {/* El eco de la derivación (aceptada o declinada) vive junto al
              mensaje del agente que la disparó (MessageList), no aquí. */}

          {/* El botón de reintentar vive junto al mensaje que se reenvía
              (MessageList), no aquí: uno solo al pie de la pantalla no
              dejaba claro qué se iba a reintentar. Esta banda solo explica
              qué pasó. */}
          {state.error && (
            <Alert
              variant="destructive"
              className="mx-auto flex w-full max-w-2xl items-center gap-3"
            >
              <TriangleAlert aria-hidden="true" />
              <AlertDescription>{state.error.message}</AlertDescription>
            </Alert>
          )}

          <Composer disabled={state.streaming} onSend={(text) => void send(text)} />
        </div>
      </main>

      {/* Proveedor propio, aparte del de la sidebar de conversaciones: cada
          panel anima su propio ancho/estado, y este solo existe desde lg
          (igual que antes, cuando el panel ni se montaba por debajo de ese
          punto de quiebre). */}
      <SidebarProvider
        open={showDevPanel}
        onOpenChange={toggleDevPanel}
        style={{ '--sidebar-width': '17.5rem' } as CSSProperties}
        className="hidden lg:contents"
      >
        <DevPanel
          lead={state.lead}
          stage={state.stage}
          metrics={state.metrics}
          onClose={() => toggleDevPanel(false)}
          onOpenSession={(id) => void openSession(id)}
          feedbackVersion={feedbackVersion}
        />
      </SidebarProvider>
    </SidebarProvider>
  )
}

function readDevPanelPreference(): boolean {
  try {
    return localStorage.getItem(DEV_PANEL_KEY) !== 'false'
  } catch {
    return true
  }
}
