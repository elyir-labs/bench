// Your printers follow your account, done (design/account-list/, A): what account-list.ts decides, carried out.
// Runs whenever Bench Cloud has answered or a printer's reach changed; one run at a time.

import { computed, watch } from 'vue'
import { guessDeviceName } from '@/door'
import { account, api, call, refreshAccount } from './account'
import { follow, toJoin, type AccountDevice } from './account-list'
import { forgetPrinter, listed, markAccount, printers, savePrinter } from './printers'

// Pick 2, as said on 12 November 2026: signed in, a printer on this phone goes into the account by itself. Nothing
// asks. One added before signing in goes in at sign-in; one added away from home goes in the next time at home.
const AGAIN_MS = 10 * 60 * 1000
const tried = new Map<string, number>()
const due = (key: string) => (tried.get(key) ?? 0) < Date.now() - AGAIN_MS

const devices = (): AccountDevice[] => (account.me?.devices ?? []) as AccountDevice[]
const settled = () => listed.value && account.state === 'in' && account.fresh && !!account.me?.house?.id
export const waiting = computed(() => (settled() ? toJoin(devices(), printers) : []))
export const inAccountCount = computed(() => printers.filter((p) => p.account).length)

/** Signed in with no house yet: the account gets a free one, so this phone's printers have somewhere to be. */
let housing = false
async function makeHouse(): Promise<void> {
  if (housing || !due('house')) return
  housing = true
  tried.set('house', Date.now())
  try {
    await call('POST', '/v1/house')
    await refreshAccount()
  } catch { /* asked again later */ } finally {
    housing = false
  }
}

/** A pass from Bench Cloud, handed to the printer's door: at home first, then by its public name. */
async function letIn(d: AccountDevice, house: string): Promise<void> {
  const { pass } = await call('POST', '/v1/passes', { device: d.id })
  for (const via of ['home', 'away'] as const) {
    const base = d.door?.addresses[via]
    if (!base) continue
    let r: Response
    try {
      r = await fetch(`${base}/door/account`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pass, name: guessDeviceName() }), signal: AbortSignal.timeout(via === 'home' ? 2500 : 12_000) })
    } catch {
      continue                                // never got there: the pass is still good for the other name
    }
    if (!r.ok) return                         // the door answered no; the pass is spent
    const got = await r.json()
    await savePrinter({ id: got.printer.id, name: got.printer.name, addresses: got.addresses, token: got.token,
      added: Date.now(), account: d.id, house, letIn: true })
    return
  }
}

/** Puts a printer this phone has at home into the account (the door refuses it from away). */
async function join(p: { id: string; name: string; base: string | null; token: string }): Promise<boolean> {
  const t = await call('POST', '/v1/join-tokens', { name: p.name, kind: 'printer' })
  const r = await fetch(`${p.base}/door/cloud/join`, { method: 'POST',
    headers: { Authorization: `Bearer ${p.token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ join_token: t.join_token, api }), signal: AbortSignal.timeout(20_000) })
  return r.ok
}

let running = false
export async function followAccount(): Promise<void> {
  if (listed.value && account.state === 'no-house' && printers.length) return makeHouse()
  if (running || !settled()) return
  running = true
  try {
    const house = account.me!.house!.id
    const plan = follow(devices(), house, printers)
    for (const id of plan.drop) await forgetPrinter(id)
    for (const l of plan.link) await markAccount(l.id, l.device, house)
    for (const d of plan.letIn) {
      if (!due(`in:${d.id}`)) continue
      tried.set(`in:${d.id}`, Date.now())
      await letIn(d, house).catch(() => {})
    }
    let joined = false
    for (const w of toJoin(devices(), printers)) {
      const p = printers.find((x) => x.id === w.id)
      if (!p || p.reach !== 'home' || !p.base || !due(`join:${p.id}`)) continue
      tried.set(`join:${p.id}`, Date.now())
      joined = (await join(p).catch(() => false)) || joined
    }
    if (joined) setTimeout(() => void refreshAccount(), 4000)   // after the doors have said where they answer
  } finally {
    running = false
  }
}

export function startFollowing(): void {
  watch(() => [listed.value, account.fresh, account.state, account.me, printers.map((p) => p.reach).join()], () => void followAccount())
  // signed out here: what only the account opened goes with it; printers paired by hand stay
  watch(() => account.owner, async (o, was) => {
    if (o || !was) return
    for (const p of [...printers]) {
      if (p.letIn) await forgetPrinter(p.id)
      else if (p.account) await markAccount(p.id, null)
    }
  })
}
