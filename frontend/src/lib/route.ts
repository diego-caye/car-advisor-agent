/**
 * Minimal hand-rolled router: the app only has two kinds of URLs, so pulling
 * in a full routing library would be more code than it solves, not less.
 *
 *   /            draft conversation, not yet created in the backend
 *   /c/:id       an existing conversation, navigable and shareable
 */

const SESSION_PATH_RE = /^\/c\/([^/]+)\/?$/

export function sessionIdFromPath(pathname: string): string | null {
  const match = SESSION_PATH_RE.exec(pathname)
  return match?.[1] ? decodeURIComponent(match[1]) : null
}

export function sessionPath(sessionId: string): string {
  return `/c/${encodeURIComponent(sessionId)}`
}

/**
 * Changes the URL without reloading the page, but leaves a real URL (to
 * share, bookmark, or use back/forward) instead of just React state.
 *
 * Does NOT fire a 'popstate' by hand: whoever calls navigate() already
 * handles its own state (setSessionId updates sessionIdState in the same
 * moment; the failed-load catch already does its own reset). It used to
 * emit a synthetic one "so route listeners find out", but that triggered
 * redundant effects on the listener itself (`onPopState` in useChat.ts,
 * which already finds out some other way) -- a real bug, found live: when
 * sending the first message of a new session, that synthetic popstate
 * relaunched loadSessionData() for a session the backend didn't have
 * populated yet, and its `load` with `messages: []` stomped on the message
 * just added optimistically. The 'popstate' listener still serves the
 * browser's REAL back/forward, which does fire the native event on its
 * own, without this function's help.
 */
export function navigate(path: string): void {
  if (window.location.pathname === path) return
  window.history.pushState(null, '', path)
}
