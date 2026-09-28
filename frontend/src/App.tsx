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
      // Non-essential preference: if storage fails, it just isn't remembered.
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

          {/* The handoff echo (accepted or declined) lives next to the
              agent message that triggered it (MessageList), not here. */}

          {/* The retry button lives next to the message being resent
              (MessageList), not here: a single one at the bottom of the
              screen didn't make clear what was going to be retried. This
              banner just explains what happened. */}
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

      {/* Its own provider, separate from the conversations sidebar's: each
          panel animates its own width/state, and this one only exists from
          lg up (same as before, when the panel wasn't even mounted below
          that breakpoint). */}
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
