// Every printer this phone is paired with, and how to reach each one right now.
//
// Home first (docs/door.md): try the printer's home name with the token for about 1.5 s; if it
// answers paired, use it, otherwise the public name. Ask again when the phone comes back online,
// when the app comes back to the foreground, and whenever a printer's connection drops. Each
// printer keeps one live connection for the list's status; its own screens open in a frame.

import { reactive, ref } from 'vue'
import { IntentClient } from '@/intent/client'
import type { Intent } from '@/intent/types'
import { del, getAll, put } from './db'

export interface Addresses {
  home: string | null   // https://192-0-2-73.workshop.home.elyir.app
  away: string | null   // https://workshop.elyir.app
}

export interface PrinterRecord {
  id: string
  name: string
  addresses: Addresses
  token: string
  added: number
  kind?: 'bench'        // a Bench Box (design/bench-look/, C): reached by its public name, its printers asked through it
}

/** A Bench Box this phone is paired with: kept apart from the printers (no live connection, notifications or screens
 *  of its own here), for How would it print? and a row in the list. */
export interface LiveBench extends PrinterRecord {
  reach: 'checking' | 'away' | 'offline' | 'unpaired'
  base: string | null
  printers: { id: string; name: string }[]
}
export const benches = reactive<LiveBench[]>([])

export type Reach = 'checking' | 'home' | 'away' | 'offline' | 'unpaired'

export interface LivePrinter extends PrinterRecord {
  reach: Reach
  base: string | null          // the address in use, or null
  intent: Intent | null
  connected: boolean
}

const HOME_PROBE_MS = 1500
const AWAY_PROBE_MS = 8000

export const printers = reactive<LivePrinter[]>([])
/** The saved list has been read: until then an empty list means nothing yet, not no printers. */
export const listed = ref(false)
const clients = new Map<string, IntentClient>()

export interface DoorMe {
  paired: boolean
  role: 'home' | 'away'
  printer: { id: string; name: string }
  addresses: Addresses
  actions: string[] | null
}

export async function doorMe(base: string, token: string, ms: number): Promise<DoorMe | null> {
  try {
    const r = await fetch(`${base}/door/me`, {
      headers: { Authorization: `Bearer ${token}` }, cache: 'no-store', signal: AbortSignal.timeout(ms),
    })
    return r.ok ? ((await r.json()) as DoorMe) : null
  } catch {
    return null   // unreachable, Chrome's local-network prompt declined or pending, DNS rebind protection...
  }
}

function byId(id: string): LivePrinter | undefined {
  return printers.find((p) => p.id === id)
}

export function recordOf(p: LivePrinter): PrinterRecord {
  return { id: p.id, name: p.name, addresses: { ...p.addresses }, token: p.token, added: p.added, ...(p.kind ? { kind: p.kind } : {}) }
}

const inFlight = new Map<string, Promise<void>>()

// An address that answered /door/me but whose live connection then never came up (a router or the
// phone letting plain requests through but not the websocket, a printer restarting mid-way): skip
// it for a while, so the printer doesn't sit on "Connecting…" when its other name would work.
const AVOID_MS = 10 * 60 * 1000
const avoid = new Map<string, Map<'home' | 'away', number>>()   // printer id -> address -> until
const avoided = (id: string, via: 'home' | 'away') => (avoid.get(id)?.get(via) ?? 0) > Date.now()

/** The live connection on the current address never came up: try the printer's other name. */
export function tryOtherAddress(id: string): Promise<void> {
  const p = byId(id)
  if (!p || (p.reach !== 'home' && p.reach !== 'away')) return Promise.resolve()
  const other = p.reach === 'home' ? 'away' : 'home'
  if (!p.addresses[other] || avoided(id, other)) return Promise.resolve()   // both tried: stay, don't flap
  if (!avoid.has(id)) avoid.set(id, new Map())
  avoid.get(id)!.set(p.reach, Date.now() + AVOID_MS)
  return reach(id)
}

/** Find the best address for one printer and (re)connect to it. One check per printer at a time. */
export function reach(id: string): Promise<void> {
  const running = inFlight.get(id)
  if (running) return running
  const job = probe(id).finally(() => inFlight.delete(id))
  inFlight.set(id, job)
  return job
}

async function probe(id: string): Promise<void> {
  const p = byId(id)
  if (!p) return
  if (p.reach === 'offline' || p.reach === 'unpaired') p.reach = 'checking'
  let found: { me: DoorMe; base: string; via: 'home' | 'away' } | null = null
  let unpaired = false
  const order = (['home', 'away'] as const).filter((v) => !avoided(id, v))
  for (const via of order.length ? order : (['home', 'away'] as const)) {
    const base = p.addresses[via]
    if (!base) continue
    const me = await doorMe(base, p.token, via === 'home' ? HOME_PROBE_MS : AWAY_PROBE_MS)
    if (me?.paired) { found = { me, base, via }; break }
    if (me && !me.paired) unpaired = true   // the printer answered and doesn't know this phone any more
  }
  if (!found) {
    p.reach = unpaired ? 'unpaired' : 'offline'
    p.base = null
    clients.get(id)?.close()
    clients.delete(id)
    p.connected = false
    return
  }
  // the door always reports its current names: the home one follows the printer's LAN address
  const { me, base, via } = found
  // a local test door on plain http reports names it doesn't actually answer on: keep ours then
  const theirs = base.startsWith('https://') ? { home: me.addresses.home ?? null, away: me.addresses.away ?? null } : p.addresses
  const changed = theirs.home !== p.addresses.home || theirs.away !== p.addresses.away || me.printer.name !== p.name
  p.addresses = theirs
  p.name = me.printer.name || p.name
  if (changed) await put('printers', recordOf(p))
  p.reach = via
  if (p.base !== base || !clients.has(id)) {
    p.base = base
    connect(p)
  }
}

function connect(p: LivePrinter) {
  clients.get(p.id)?.close()
  const ws = p.base!.replace(/^http/, 'ws') + '/websocket'
  const c = new IntentClient({ http: p.base!, ws }, ['elyir-bench', 'elyir-bench-token.' + p.token])
  clients.set(p.id, c)
  c.connect()
  // mirror the client's state into the list; a drop that lasts means the other address may be the one now
  let dropTimer = 0
  const started = Date.now()
  let gaveUp = false
  const sync = () => {
    if (clients.get(p.id) !== c) return
    const q = byId(p.id)
    if (!q) return
    q.intent = c.intent.value
    if (q.connected !== c.connected.value) {
      q.connected = c.connected.value
      window.clearTimeout(dropTimer)
      if (!q.connected) dropTimer = window.setTimeout(() => reach(p.id), 4000)
    }
    // reachable by plain requests but the live connection never comes up: the other name
    if (!q.connected && Date.now() - started > 8000 && !gaveUp) {
      gaveUp = true
      tryOtherAddress(p.id)
    }
    window.setTimeout(sync, 500)
  }
  sync()
}

export async function loadPrinters(): Promise<void> {
  const saved = (await getAll<PrinterRecord>('printers')).sort((a, b) => a.added - b.added)
  const own = saved.filter((r) => r.kind !== 'bench')
  printers.splice(0, printers.length, ...own.map((r) => ({ ...r, reach: 'checking' as Reach, base: null, intent: null, connected: false })))
  benches.splice(0, benches.length, ...saved.filter((r) => r.kind === 'bench').map((r) => ({ ...r, reach: 'checking' as const, base: null, printers: [] })))
  listed.value = true
  await Promise.all([...printers.map((p) => reach(p.id)), ...benches.map((b) => reachBench(b.id))])
}

/** A box answers at its public name only (the Printers app is https, the box at home isn't): its printers with it. */
export async function reachBench(id: string): Promise<void> {
  const b = benches.find((x) => x.id === id)
  const base = b?.addresses.away
  if (!b || !base) return
  const me = await doorMe(base, b.token, AWAY_PROBE_MS)
  if (!me) { b.reach = 'offline'; b.base = null; return }
  if (!me.paired) { b.reach = 'unpaired'; b.base = null; return }
  b.reach = 'away'
  b.base = base
  const box = (me as unknown as { box?: { name?: string } }).box
  if (box?.name && box.name !== b.name) { b.name = box.name; await put('printers', recordOf(b as unknown as LivePrinter)) }
  try {
    const r = await fetch(`${base}/bench/printers`, { headers: { Authorization: `Bearer ${b.token}` }, cache: 'no-store' })
    if (r.ok) b.printers = ((await r.json()) as { id: string; name: string }[]).map((x) => ({ id: x.id, name: x.name }))
  } catch { /* its list comes next time */ }
}

export async function savePrinter(r: PrinterRecord): Promise<void> {
  if (r.kind === 'bench') {
    await put('printers', r)
    const existing = benches.find((b) => b.id === r.id)
    if (existing) Object.assign(existing, r)
    else benches.push({ ...r, reach: 'checking', base: null, printers: [] })
    return reachBench(r.id)
  }
  await put('printers', r)
  const existing = byId(r.id)
  if (existing) Object.assign(existing, r)
  else printers.push({ ...r, reach: 'checking', base: null, intent: null, connected: false })
  await reach(r.id)
}

export async function forgetPrinter(id: string): Promise<void> {
  clients.get(id)?.close()
  clients.delete(id)
  await del('printers', id)
  const i = printers.findIndex((p) => p.id === id)
  if (i >= 0) printers.splice(i, 1)
  const j = benches.findIndex((b) => b.id === id)
  if (j >= 0) benches.splice(j, 1)
}

export function printerById(id: string): LivePrinter | undefined {
  return byId(id)
}

/** Ask every printer again where it is: back online, back in the foreground. */
export function watchNetwork(): void {
  // back online or in the foreground: a new network, so every address gets a fresh chance
  const again = () => { avoid.clear(); printers.forEach((p) => reach(p.id)); benches.forEach((b) => reachBench(b.id)) }
  window.addEventListener('online', again)
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') again() })
}
