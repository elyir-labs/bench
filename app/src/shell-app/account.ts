// The Elyir account signed in on this phone, in the Printers app (design/one-cloud/, A; words in you.ts).

import { reactive } from 'vue'
import { loadOwner, ownerCall, ownerToken, saveOwner, supabaseCall, type Owner } from '@/cloud'
import { guessDeviceName } from '@/door'
import { planOf, type CloudDevice, type Me, type PaidPlan, type Pay } from './you'
import { WEEK, keep, recall } from '@/remember'

export type AccountState = 'out' | 'checking' | 'in' | 'no-house' | 'error'

const storage = (() => { try { return window.localStorage } catch { return null } })()
// Bench Cloud under elyir.app: the Printers app's content policy only lets it talk to *.elyir.app. Printers joined from
// here use the same one (staging's Printers app puts them in staging's Bench Cloud).
export const api = (import.meta.env.VITE_CLOUD_URL as string | undefined) || 'https://cloud.elyir.app'

// Last time's account opens the page while it checks (design/loading/, B + A); `fresh` once Bench Cloud has answered.
const ME_KEY = 'elyir.cloud.me'
const owner = loadOwner(storage)
const lastMe = owner ? recall<Me>(storage, ME_KEY, owner.email, WEEK) : null
export const account = reactive<{ owner: Owner | null; me: Me | null; state: AccountState; error: string | null; pay: Pay | null; checking: boolean; fresh: boolean }>({
  owner, me: lastMe, state: lastMe ? 'in' : 'out', error: null, pay: null, checking: false, fresh: false,
})

/** Whether paying is open (Stripe set up on Bench Cloud); until then the plan is by tester invite only. */
export async function loadPay(): Promise<void> {
  try {
    const r = await fetch(`${api}/v1/config`, { cache: 'no-store' })
    account.pay = r.ok ? ((await r.json()).pay ?? null) : null
  } catch {
    account.pay = null
  }
}

export function setOwner(o: Owner | null): void {
  account.owner = o
  saveOwner(storage, o)
  if (!o) { account.me = null; account.state = 'out'; account.fresh = false; keep(storage, ME_KEY, '', null) }
}

export const call = (method: string, path: string, body?: unknown) =>
  ownerCall(account.owner!, setOwner, guessDeviceName(), method, path, body)

export async function refreshAccount(): Promise<void> {
  if (!account.owner) { account.state = 'out'; return }
  if (!account.me) account.state = 'checking'
  account.checking = true
  try {
    const me = await call('GET', '/v1/me')
    me.plan ??= planOf(me.house?.plan)   // a Bench Cloud from before design/one-cloud/
    account.me = me
    account.state = 'in'
    account.error = null
    account.fresh = true
    if (account.owner) keep(storage, ME_KEY, account.owner.email, me)
  } catch (e) {
    const why = (e as Error).message
    if (/isn't an owner/.test(why)) { account.me = null; account.state = 'no-house'; account.fresh = true; keep(storage, ME_KEY, '', null) }
    else if (/^Sign in/.test(why)) setOwner(null)
    else { account.error = why; if (!account.me) account.state = 'error' }
  } finally {
    account.checking = false
  }
}

/** Stripe's own checkout page; it comes back to /you?paid=1, and the plan goes on when Stripe tells Bench Cloud. */
export async function checkout(plan: PaidPlan): Promise<void> {
  location.href = (await call('POST', '/v1/checkout', { plan })).url
}

/** Stripe's customer portal: change the plan, stop it, receipts. */
export async function manage(): Promise<void> {
  location.href = (await call('POST', '/v1/billing')).url
}

export async function startHouse(invite: string): Promise<void> {
  await call('POST', '/v1/start', { invite: invite.trim() })
  await refreshAccount()
}

/** Signs this phone out (its own Supabase session only; the others stay). */
/** A second owner, by email: an invite Bench Cloud mails them, that waits until they accept it (design/account/, A). */
export async function addOwner(email: string): Promise<void> {
  await call('POST', '/v1/owners', { email })
  await refreshAccount()
}

/** An owner invite, opened from its email: whose it is, and whether it's for the email signed in here. */
export const getInvite = (token: string) => call('GET', `/v1/owner-invites/${encodeURIComponent(token)}`)
export async function acceptInvite(token: string): Promise<void> {
  await call('POST', `/v1/owner-invites/${encodeURIComponent(token)}/accept`)
  await refreshAccount()
}
export const declineInvite = (token: string) => call('POST', `/v1/owner-invites/${encodeURIComponent(token)}/decline`)
export async function cancelInvite(id: string): Promise<void> {
  await call('DELETE', `/v1/invites/owner/${encodeURIComponent(id)}`)
  await refreshAccount()
}

/** Takes an owner off the house; Bench Cloud never lets the last one go. */
export async function removeOwner(id: string): Promise<void> {
  await call('DELETE', `/v1/owners/${encodeURIComponent(id)}`)
  await refreshAccount()
}

/** Tell me when Workshop opens (design/plan-size/, A). */
export async function askWorkshop(): Promise<void> {
  await call('POST', '/v1/workshop-interest')
  await refreshAccount()
}

export async function signOut(): Promise<void> {
  const o = account.owner
  if (o?.supabase && o.access) await supabaseCall(o.supabase, '/logout?scope=local', {}, o.access).catch(() => {})
  setOwner(null)
}

export async function removePhone(id: string): Promise<void> {
  await call('DELETE', `/v1/sessions/${encodeURIComponent(id)}`)
  await refreshAccount()
}

/** Puts a paired printer in the house through its own door, at home (the door refuses it away). */
export async function addPrinter(base: string, token: string, name: string): Promise<void> {
  const t = await call('POST', '/v1/join-tokens', { name, kind: 'printer' })
  const r = await fetch(`${base}/door/cloud/join`, {
    method: 'POST', headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ join_token: t.join_token, api }),
  })
  if (!r.ok) throw new Error(`${name} couldn't join Bench Cloud. Try again at home.`)
  await refreshAccount()
}

export async function downloadBackup(d: CloudDevice): Promise<void> {
  const o = account.owner!
  const t = await ownerToken(o, setOwner)
  if (!t || !d.backup) throw new Error('Sign in again to download it.')
  const r = await fetch(`${o.api}/v1/backups/${d.backup.id}/file`, { headers: { Authorization: `Bearer ${t}` } })
  if (!r.ok) throw new Error("That backup couldn't be downloaded.")
  const name = /filename="([^"]+)"/.exec(r.headers.get('Content-Disposition') ?? '')?.[1] ?? `${d.name}-backup.tar.gz`
  const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(await r.blob()), download: name })
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 10_000)
}

const DISMISS = 'printers.pitch.dismissed'
export const pitchDismissed = () => { try { return storage?.getItem(DISMISS) === '1' } catch { return false } }
export const dismissPitch = () => { try { storage?.setItem(DISMISS, '1') } catch { /* private browsing */ } }

