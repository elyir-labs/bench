// Who this page is for, asked once at start (away.ts says what follows from it), and what the box's own screen
// polls at home: the guests watching now.

import { reactive } from 'vue'
import { HOME, hereOf, type Here, type InviteRecord, type Lasts, type Look, type PhonesList, type Reach, type BoxRemote } from './away'

export const here = reactive<Here>({ ...HOME, checked: false })

export async function checkHere(): Promise<void> {
  try {
    const r = await fetch('/door/me', { credentials: 'include', cache: 'no-store' })
    const d = r.headers.get('content-type')?.includes('json') ? await r.json() : null
    Object.assign(here, hereOf(d))
  } catch {
    Object.assign(here, HOME)
  }
  here.checked = true
}

/** Away, an API path answered 401: this browser isn't (or is no longer) let in. */
export function letGo(): void {
  if (here.away) here.paired = false
}

async function answer<T>(r: Response, fallback: string): Promise<T> {
  const body = await r.json().catch(() => ({}))
  if (!r.ok) {
    const e = new Error(body.message || body.error || fallback) as Error & { detail?: string; status?: number }
    e.detail = body.detail
    e.status = r.status
    throw e
  }
  return body as T
}
const post = (body: unknown): RequestInit => ({ method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

// ── from away ──

export const pairBox = (code: string, name: string) =>
  fetch('/door/pair', post({ code: code.replace(/[^a-z0-9]/gi, '').toUpperCase(), name })).then((r) => answer<unknown>(r, "That code didn't work."))
export const lookAt = (code: string) => fetch('/door/join/look', post({ code })).then((r) => answer<Look>(r, "This link doesn't work any more."))
export const join = (code: string, name: string) => fetch('/door/join', post({ code, name })).then((r) => answer<unknown>(r, "This link doesn't work any more."))

export interface MadeInvite extends InviteRecord { code: string; url: string }

/** A paired phone away (POST /door/invites), or the box's own screen at home (POST /bench/invites). */
export function invite(reach: Reach, lasts: Lasts, by?: string): Promise<MadeInvite> {
  const url = here.away ? '/door/invites' : '/bench/invites'
  return fetch(url, post({ reach, lasts, ...(by ? { by } : {}) })).then((r) => answer<MadeInvite>(r, "The invite couldn't be made."))
}

// ── at home: the box's own screen ──

export const watching = reactive({ names: [] as string[] })

export async function loadWatching(): Promise<void> {
  try {
    const r = await fetch('/bench/watching', { cache: 'no-store' })
    if (r.ok) watching.names = ((await r.json()).watching ?? []) as string[]
  } catch {
    // the box's service restarting: the line stays as it was
  }
}

export async function getPhones(): Promise<PhonesList | null> {
  try {
    const r = await fetch('/bench/phones', { cache: 'no-store' })
    return r.ok ? ((await r.json()) as PhonesList) : null
  } catch {
    return null
  }
}

export const removePhone = (id: string) => fetch(`/bench/phones/${encodeURIComponent(id)}`, { method: 'DELETE' })
  .then((r) => { if (!r.ok && r.status !== 404) throw new Error("The box didn't remove it.") })
export const cancelInvite = (id: string) => fetch(`/bench/invites/${encodeURIComponent(id)}`, { method: 'DELETE' })
  .then((r) => { if (!r.ok && r.status !== 404) throw new Error("The box didn't cancel it.") })

export interface PairCode { code: string; url: string; expires: number }
export const newCode = () => fetch('/bench/phones/code', post({})).then((r) => answer<PairCode>(r, "Phones can't be added right now."))

export async function getRemote(): Promise<BoxRemote | null> {
  try {
    const r = await fetch('/bench/box/remote', { cache: 'no-store' })
    return r.ok ? ((await r.json()) as BoxRemote) : null
  } catch {
    return null
  }
}

/** Turns the box's own name on ({invite} the first time); the words when it can't, or why it isn't open yet. */
export async function turnRemote(on: boolean, invite?: string): Promise<{ error: string | null; why: string | null }> {
  try {
    const r = await fetch('/bench/box/remote', on ? post(invite ? { invite } : {}) : { method: 'DELETE' })
    const body = await r.json().catch(() => ({}))
    if (!r.ok) return { error: body.error || body.message || "The box didn't turn it on.", why: null }
    return { error: null, why: body.why ?? null }
  } catch {
    return { error: "The box didn't answer.", why: null }
  }
}
