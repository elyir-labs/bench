// Embed mode: the printer's screens inside the Printers app (https://printers.elyir.app).
//
// Inside the shell the printer can be reached under two names (home and away), so the door's
// cookie can't follow; the shell hands this frame its token instead (docs/door.md, "One app for
// every printer"). It arrives by postMessage, stays in memory only, and goes out as a bearer
// header, the websocket subprotocol, or ?access_token= on the camera and thumbnails.
// Outside the shell there is no token and everything works by cookie, as before.

import { BASE } from '@/base'

export const SHELL_ORIGINS = ['https://printers.elyir.app', 'http://localhost:5173', 'http://localhost:5174']   // 5174: the Bench Box's screen in dev

export const embedded = (() => {
  try {
    return window.parent !== window && new URLSearchParams(window.location.search).get('embed') === '1'
  } catch {
    return false
  }
})()

/** Inside a Bench Box (design/bench-box/, D): the box draws the top row and the sections, so this frame
 *  draws neither, and lays itself out as on the printer's own panel, at the box's size. */
export const benchChrome = embedded && (() => {
  try { return new URLSearchParams(window.location.search).get('chrome') === 'bench' } catch { return false }
})()

export const auth = { token: null as string | null }

/** Pages this frame may take its token from and report to: the Printers app's, and every Bench Box this
 *  printer said yes to (its door lists them at /door/frames, docs/bench.md). */
export const parents = new Set<string>(SHELL_ORIGINS)
export async function learnParents(): Promise<void> {
  try {
    const r = await fetch(`${BASE}/door/frames`, { cache: 'no-store', credentials: 'include' })
    const frames = r.ok ? (await r.json()).frames : null
    if (Array.isArray(frames)) frames.forEach((o) => typeof o === 'string' && parents.add(o))
  } catch {
    // no door (a printer reached directly, the simulator): the shell's own addresses only
  }
}

/** Ask the shell for this printer's token. Resolves null if no shell answers in time. */
export function receiveToken(timeoutMs = 8000): Promise<string | null> {
  if (!embedded) return Promise.resolve(null)
  return new Promise((resolve) => {
    const done = (t: string | null) => {
      window.removeEventListener('message', onMessage)
      window.clearTimeout(timer)
      window.clearInterval(asking)
      resolve(t)
    }
    const onMessage = (ev: MessageEvent) => {
      if (ev.source !== window.parent || !parents.has(ev.origin)) return
      if (ev.data?.type === 'elyir-bench:token' && typeof ev.data.token === 'string') {
        auth.token = ev.data.token
        done(ev.data.token)
      }
    }
    window.addEventListener('message', onMessage)
    // the shell may still be setting up its listener: ask again until it answers
    const ask = () => window.parent.postMessage({ type: 'elyir-bench:ready' }, '*')   // carries nothing secret
    ask()
    const asking = window.setInterval(ask, 500)
    const timer = window.setTimeout(() => done(null), timeoutMs)
  })
}

/** Headers for a door or Moonraker request from this page. */
export function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return auth.token ? { ...extra, Authorization: `Bearer ${auth.token}` } : extra
}

/** For <img>: the camera and thumbnails take the token in the query (the door allows nothing else). */
export function withToken(url: string | null): string | null {
  if (!url || !auth.token) return url
  return url + (url.includes('?') ? '&' : '?') + 'access_token=' + encodeURIComponent(auth.token)
}

/** Websocket subprotocols: the door selects 'elyir-bench' and reads the token from the other. */
export function wsProtocols(): string[] | undefined {
  return auth.token ? ['elyir-bench', 'elyir-bench-token.' + auth.token] : undefined
}

/** Tell the shell whether this frame's live connection is up, so it can try the printer's other name. */
export function reportConnection(connected: () => boolean): void {
  if (!embedded) return
  let last: boolean | null = null
  window.setInterval(() => {
    const c = connected()
    if (c !== last) {
      last = c
      window.parent.postMessage({ type: 'elyir-bench:status', connected: c }, '*')
    }
  }, 1000)
}

/** Tell the shell where this frame is, and follow it when it asks to go somewhere. takeModels: files the
 *  shell hands over for this printer's Print ("Print on Workshop…" from Look at a model, design/look/). */
export function linkToShell(currentPath: () => string, go: (path: string) => void, takeModels?: (files: File[]) => void): void {
  if (!embedded) return
  hideWithShell()
  window.addEventListener('message', (ev) => {
    if (ev.source !== window.parent || !parents.has(ev.origin)) return
    if (ev.data?.type === 'elyir-bench:navigate' && typeof ev.data.path === 'string' && ev.data.path.startsWith('/')) go(ev.data.path)
    if (ev.data?.type === 'elyir-bench:shown' && typeof ev.data.shown === 'boolean') setHiddenByShell(!ev.data.shown)
    if (ev.data?.type === 'elyir-bench:model' && takeModels && Array.isArray(ev.data.files)) {
      const files = ev.data.files.filter((f: unknown): f is File => f instanceof File)
      if (files.length) {
        takeModels(files)
        window.parent.postMessage({ type: 'elyir-bench:model-taken' }, ev.origin)
      }
    }
  })
  window.parent.postMessage({ type: 'elyir-bench:listening', hides: true }, '*')   // carries nothing; a file waiting for this printer comes now
  let last = ''
  window.setInterval(() => {
    const p = currentPath()
    if (p !== last) {
      last = p
      window.parent.postMessage({ type: 'elyir-bench:path', path: p }, '*')
    }
  }, 400)
}

// The shell keeps printers you've opened loaded behind the one you're looking at. To the browser a hidden frame is still
// a visible page, so the frame says hidden itself, and whatever already pauses for a hidden page (the camera) pauses.
let hiddenByShell = false
function hideWithShell(): void {
  const native = Object.getOwnPropertyDescriptor(Document.prototype, 'visibilityState')?.get
  if (!native) return
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => (hiddenByShell ? 'hidden' : native.call(document)) })
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => document.visibilityState === 'hidden' })
}
function setHiddenByShell(hidden: boolean): void {
  if (hidden === hiddenByShell) return
  hiddenByShell = hidden
  document.dispatchEvent(new Event('visibilitychange'))
}
