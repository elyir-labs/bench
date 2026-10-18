// The web demo's stand-in for Moonraker's websocket (VITE_DEMO=1, `npm run build:demo`).
// IntentClient opens one of these instead of a WebSocket. Behind it, demo/sim-worker.js runs the
// simulator and the real intent engine in Pyodide. Inside the showcase page (?host=parent) the
// page owns the worker, so the panel and the phone beside it share one printer; opened on its
// own, the app starts a worker of its own.

// Checked as import.meta.env.VITE_DEMO === '1' where it is used, so a printer's build drops all of this.

/** Where the demo's files live: the folder above app/. */
export const demoBase = (): string => new URL('../', document.baseURI).href

type Status = { phase: 'loading' | 'ready' | 'error'; detail: string }
export const demoStatus: { value: Status; listeners: Set<(s: Status) => void> } = {
  value: { phase: 'loading', detail: 'Starting Python' },
  listeners: new Set(),
}

let ownWorker: Worker | null = null

function openPort(): MessagePort {
  const channel = new MessageChannel()
  const viaPage = new URLSearchParams(window.location.search).get('host') === 'parent' && window.parent !== window
  if (viaPage) {
    window.parent.postMessage({ t: 'connect' }, '*', [channel.port2])
  } else {
    // ?scenario=runout&speed=1 on the app's own address picks the moment it opens on (a printer's screen for a photo)
    const worker = new URL('sim-worker.js', demoBase())
    const own = new URLSearchParams(window.location.search)
    for (const k of ['scenario', 'speed']) if (own.get(k)) worker.searchParams.set(k, own.get(k)!)
    ownWorker ??= new Worker(worker, { type: 'module' })
    ownWorker.postMessage({ t: 'connect' }, [channel.port2])
  }
  return channel.port1
}

/** The parts of WebSocket that IntentClient uses. */
export class DemoSocket {
  static readonly OPEN = 1
  readyState = 0
  onopen: ((ev: Event) => void) | null = null
  onmessage: ((ev: { data: string }) => void) | null = null
  onclose: ((ev: Event) => void) | null = null
  onerror: ((ev: Event) => void) | null = null
  private port = openPort()

  constructor() {
    this.port.onmessage = (ev) => {
      const m = ev.data
      if (m.t === 'ws') this.onmessage?.({ data: m.text })
      else if (m.t === 'status') {
        demoStatus.value = { phase: m.phase, detail: m.detail }
        for (const fn of demoStatus.listeners) fn(demoStatus.value)
        if (m.phase === 'ready' && this.readyState === 0) {
          this.readyState = DemoSocket.OPEN
          this.onopen?.(new Event('open'))
        }
      }
    }
  }

  send(text: string): void {
    this.port.postMessage({ t: 'rpc', text })
  }

  close(): void {
    this.readyState = 3
    this.port.close()
    this.onclose?.(new Event('close'))
  }
}
