// Every printer on the bench, live: one connection each to its intent layer, mirrored into a list the pages
// draw. The list itself is the box's (GET /bench/printers); a printer that doesn't answer is off.

import { reactive } from 'vue'
import { IntentClient } from '@/intent/client'
import type { Intent } from '@/intent/types'
import type { BenchPrinter } from './bench'
import type { QueueItem } from './shelf'
import { here, letGo, loadWatching } from './here'

export interface BenchRecord {
  id: string
  name: string
  moonraker: string        // where its intent layer answers: /bench/p/<id> (through the box), or http://host:port in dev
  app: string              // where its own screens are drawn, for the frame
  token?: string           // its door's token for this box; none for a printer reached without a door
}

export interface LiveBenchPrinter extends BenchPrinter {
  record: BenchRecord
}

export const bench = reactive({ loaded: false, error: '', printers: [] as LiveBenchPrinter[], queue: [] as QueueItem[] })
const clients = new Map<string, IntentClient>()
const OFF_AFTER_MS = 6000   // never answered, or dropped and didn't come back: off

export async function loadBench(): Promise<void> {
  try {
    const r = await fetch('/bench/printers', { cache: 'no-store' })
    if (r.status === 401) return letGo()
    const list = (await r.json()) as BenchRecord[]
    // keep the ones already live; connect the ones that just joined; drop the ones taken off
    for (const p of bench.printers.filter((p) => !list.some((rec) => rec.id === p.id))) clients.get(p.id)?.close()
    bench.printers = list.map((rec) => bench.printers.find((p) => p.id === rec.id) ?? { id: rec.id, name: rec.name, live: false, intent: null, record: rec })
    bench.printers.filter((p) => !clients.has(p.id)).forEach(connect)
  } catch (e) {
    bench.error = "The box's list of printers didn't load."
  } finally {
    bench.loaded = true
  }
}

/** The box's queue, looked at every few seconds (it moves when printers come free). */
export async function loadQueue(): Promise<void> {
  try {
    const r = await fetch('/bench/queue', { cache: 'no-store' })
    if (r.status === 401) letGo()
    if (r.ok) bench.queue = await r.json()
  } catch {
    // the box's service restarting: the last known queue stays on screen
  }
}

let started = false
/** The bench, live, once this page may see it: at once at home, after pairing or joining away. At home the box's
 *  screen also says who's watching from away. */
export function startBench(): void {
  if (started) return
  started = true
  void loadBench()
  void loadQueue()
  window.setInterval(loadQueue, 3000)
  if (!here.away) {
    void loadWatching()
    window.setInterval(loadWatching, 10000)
  }
}

function connect(p: LiveBenchPrinter): void {
  const c = new IntentClient(endpointOf(p.record), p.record.token ? ['elyir-bench', 'elyir-bench-token.' + p.record.token] : undefined)
  clients.set(p.id, c)
  c.connect()
  let lastSeen = 0
  const sync = () => {
    const q = bench.printers.find((x) => x.id === p.id)
    if (!q) return
    if (c.connected.value && c.intent.value) lastSeen = Date.now()
    q.intent = c.intent.value as Intent | null
    q.live = !!q.intent && (c.connected.value || Date.now() - lastSeen < OFF_AFTER_MS)
    window.setTimeout(sync, 500)
  }
  sync()
}

/** A printer's live connection, to ask it something (check_print) or press a button (start_file) as its own screen does. */
export const clientOf = (id: string): IntentClient | null => clients.get(id) ?? null

/** Where to reach a printer's intent layer: through the box (a path), or directly in dev (http://host:port). */
export function endpointOf(r: BenchRecord): { http: string; ws: string } {
  const http = new URL(r.moonraker, window.location.href).href.replace(/\/$/, '')
  return { http, ws: http.replace(/^http/, 'ws') + '/websocket' }
}

/** A printer's own file, such as its job's picture, from where it's served. */
export function fileOf(p: LiveBenchPrinter, path: string | null): string | null {
  if (!path) return null
  const t = p.record.token ? `?access_token=${encodeURIComponent(p.record.token)}` : ''
  return `${p.record.moonraker}/server/files/gcodes/${path.split('/').map(encodeURIComponent).join('/')}${t}`
}
