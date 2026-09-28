import type { MouseEvent } from 'react'
import { MessageSquarePlus, Trash2 } from 'lucide-react'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import {
  Sidebar as SidebarRoot,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
} from '@/components/ui/sidebar'

import type { SessionSummary } from '../../api/types'
import { sessionPath } from '../../lib/route'
import { STAGE_LABEL } from '../chat/labels'

type Props = {
  sessions: SessionSummary[]
  activeId: string | null
  onSelect: (sessionId: string) => void
  onCreate: () => void
  onDelete: (sessionId: string) => void
}

export function Sidebar({ sessions, activeId, onSelect, onCreate, onDelete }: Props) {
  return (
    <SidebarRoot collapsible="offcanvas">
      <SidebarHeader className="p-3">
        <Button type="button" onClick={onCreate} className="h-10 w-full font-semibold">
          <MessageSquarePlus aria-hidden="true" />
          Nueva conversación
        </Button>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {sessions.length === 0 && (
                <p className="text-muted-foreground px-2 py-3 text-xs">
                  Todavía no tienes conversaciones.
                </p>
              )}

              {sessions.map((session) => {
                const isActive = session.session_id === activeId

                // Un <a href> real, no un <button>: así se puede abrir en pestaña
                // nueva con clic central o Ctrl/Cmd+clic, copiar el enlace con
                // clic derecho, o simplemente pegar la URL en otra pestaña. El
                // clic normal se intercepta para navegar sin recargar la página.
                function handleClick(event: MouseEvent<HTMLAnchorElement>) {
                  const usesModifier =
                    event.button !== 0 ||
                    event.metaKey ||
                    event.ctrlKey ||
                    event.shiftKey ||
                    event.altKey
                  if (usesModifier) return
                  event.preventDefault()
                  onSelect(session.session_id)
                }

                return (
                  <SidebarMenuItem key={session.session_id}>
                    <SidebarMenuButton asChild isActive={isActive} className="h-auto py-2 pr-8">
                      <a
                        href={sessionPath(session.session_id)}
                        onClick={handleClick}
                        aria-current={isActive ? 'true' : undefined}
                      >
                        <span className="flex min-w-0 flex-col">
                          {/* El título lo genera el modelo ligero en segundo
                              plano; hasta que llega, la conversación ya tiene
                              que poder distinguirse. */}
                          <span className="block truncate text-sm">
                            {session.titulo || 'Conversación nueva'}
                          </span>
                          <span className="text-muted-foreground block truncate text-[11px]">
                            {new Date(session.last_update_time).toLocaleString('es-PE', {
                              day: '2-digit',
                              month: 'short',
                              hour: '2-digit',
                              minute: '2-digit',
                            })}
                            {' · '}
                            {STAGE_LABEL[session.stage] ?? session.stage}
                          </span>
                        </span>
                      </a>
                    </SidebarMenuButton>

                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <SidebarMenuAction
                          showOnHover
                          aria-label="Eliminar conversación"
                          title="Eliminar conversación"
                          className="text-muted-foreground hover:text-destructive !top-1/2 !-translate-y-1/2"
                        >
                          <Trash2 aria-hidden="true" />
                        </SidebarMenuAction>
                      </AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>¿Eliminar esta conversación?</AlertDialogTitle>
                          <AlertDialogDescription>
                            Se borran los mensajes de «{session.titulo || 'Conversación nueva'}».
                            Tu ficha de datos no se pierde: vive a nivel de usuario, no de
                            conversación.
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>Cancelar</AlertDialogCancel>
                          {/* variant, no className: AlertDialogAction reenvía la
                              className al elemento interno de Radix, no al Button
                              que calcula bg-primary, así que una clase de color
                              ahí compite con esa por especificidad y a veces
                              pierde. El variant sí lo controla el propio Button. */}
                          <AlertDialogAction
                            variant="destructive"
                            onClick={() => onDelete(session.session_id)}
                          >
                            Eliminar
                          </AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  </SidebarMenuItem>
                )
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
    </SidebarRoot>
  )
}
