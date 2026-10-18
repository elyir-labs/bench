// Devices asking to connect (docs/door.md): a phone or computer on the printer's Wi-Fi asks, and
// somebody here says yes. No code to read or type.
//
// Who may answer: the panel and the house Wi-Fi page (no door in front, role null) and a paired
// phone at home (role home). Not from away: the owner's rule, and the door enforces it too.
// The door announces every new ask and every answer as a Moonraker agent event, so this list is
// live; a slow poll of /door/asks covers a missed event.

import { reactive } from 'vue'
import { authHeaders } from '@/auth'
import { door } from '@/door'
import { BASE } from '@/base'
import { loadOwner, ownerCall, saveOwner, type Owner } from '@/cloud'
import { guessDeviceName } from '@/door'

export interface Ask {
  id: string
  name: string
  kind: 'phone' | 'tablet' | 'computer' | 'hub' | 'device' | 'printer' | 'bench' | 'backup'   // printer: wants to slice here (/slice/asks)
  at: number
  expires: number   // epoch seconds
  backup_at?: number | null   // backup: a new card asks Bench Cloud for this printer's backup (docs/cloud.md)
}

export const asks = reactive({
  list: [] as Ask[],
  inline: false,     // the panel's Add a phone sheet is open and shows them itself
})

export function canAnswer(): boolean {
  return door.checked && !door.away
}

export function kindWords(k: Ask['kind']): string {
  return { phone: 'A phone', tablet: 'A tablet', computer: 'A computer', hub: 'A home hub', device: 'A device', printer: 'A printer', bench: 'A computer', backup: 'A new card' }[k] ?? 'A device'
}

// Two kinds of asking: devices ask the door to connect, printers ask this printer's slicer to slice for them
// (design/slicing-elsewhere/, A). Kept apart, so the door's event never drops a printer that's waiting.
// A third: a new card asks Bench Cloud for its printer's backup (design/cloud/ C-phone-allow), answered by the house's
// owner signed in on this phone, at home or away (the card has to be at home for the cloud to take its ask).
const from = { door: [] as Ask[], slicer: [] as Ask[], cloud: [] as Ask[] }
const merge = () => { asks.list = [...from.cloud, ...from.door, ...from.slicer] }
const CLOUD_ID = 'cloud:'
const store = () => { try { return window.localStorage } catch { return null } }
const owner = () => loadOwner(store())
const keep = (o: Owner | null) => saveOwner(store(), o)

async function loadCloud(): Promise<void> {
  const o = owner()
  if (!o) { from.cloud = []; return }
  try {
    const d = await ownerCall(o, keep, guessDeviceName(), 'GET', '/v1/asks')
    from.cloud = (d.asks ?? []).map((a: { id: string; name: string; at: number; backup_at: number | null }) => (
      { id: CLOUD_ID + a.id, name: a.name, kind: 'backup', at: a.at, expires: a.at + 1800, backup_at: a.backup_at }))
  } catch {
    from.cloud = []
  }
}

/** A backup ask is the owner's to answer wherever they are; everything else, only here at home. */
export const canAnswerAsk = (a: Ask) => a.kind === 'backup' || canAnswer()

async function load(): Promise<void> {
  await loadCloud()
  merge()
  if (!canAnswer()) return
  try {
    const r = await fetch(`${BASE}/door/asks`, { cache: 'no-store', headers: authHeaders() })
    if (r.ok) from.door = ((await r.json()).asks ?? []) as Ask[]
  } catch {
    // no door here: nobody can ask this printer
  }
  try {
    // a printer waits as long as it takes: no countdown
    const r = await fetch(`${BASE}/slice/asks`, { cache: 'no-store', headers: authHeaders() })
    const d = r.ok ? await r.json() : null
    from.slicer = Array.isArray(d?.asks) ? d.asks.map((a: Ask) => ({ ...a, kind: 'printer', expires: Number.MAX_SAFE_INTEGER })) : []
  } catch {
    from.slicer = []    // no slicer here, or one elsewhere: nobody asks this printer to slice
  }
  merge()
}

export async function answer(id: string, allow: boolean): Promise<void> {
  if (id.startsWith(CLOUD_ID)) {
    const o = owner()
    if (!o) throw new Error('Sign in to your Bench Cloud first.')
    try {
      await ownerCall(o, keep, guessDeviceName(), 'POST', `/v1/asks/${encodeURIComponent(id.slice(CLOUD_ID.length))}/${allow ? 'allow' : 'refuse'}`, {})
    } finally {
      from.cloud = from.cloud.filter((a) => a.id !== id)
      merge()
    }
    return
  }
  const printer = from.slicer.some((a) => a.id === id)
  const r = await fetch(`${BASE}/${printer ? 'slice' : 'door'}/asks/${encodeURIComponent(id)}/${allow ? 'allow' : 'refuse'}`, {
    method: 'POST', headers: authHeaders(),
  })
  if (r.ok || r.status === 404) {
    from.door = from.door.filter((a) => a.id !== id)
    from.slicer = from.slicer.filter((a) => a.id !== id)
    merge()
  }
  if (!r.ok && r.status !== 404) {
    const why = await r.json().then((d) => d?.error, () => null)
    throw new Error(why || "Couldn't answer. Try again.")
  }
  load()
}

type On = (method: string, fn: (params: any[]) => void) => unknown

/** Keep the list current: the door's event at once, a poll every 15 s as a backstop. */
export function followAsks(on: On): () => void {
  on('notify_agent_event', (params) => {
    const e = params?.[0]
    if (e?.agent === 'elyir-bench-door' && e?.event === 'elyir_bench_asks' && Array.isArray(e.data?.asks)) {
      if (canAnswer()) { from.door = e.data.asks; merge() }
    }
  })
  load()
  const timer = window.setInterval(load, 15000)
  return () => window.clearInterval(timer)
}
