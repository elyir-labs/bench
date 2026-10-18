// The door: how a phone reaches the printer from outside the house (docs/door.md).
//
// Away, the app is served by the door on the printer's public name. It only lets in paired
// phones, and from away only a short list of actions (GET /door/me says which). At home
// (nginx on :8088, or the panel) /door/me doesn't exist, so everything stays as it was.
//
// Pairing happens at the printer: the panel asks for a code (POST /door/pair/new) and shows
// it as a QR code; the phone sends it back with a name (POST /door/pair) and gets a cookie.

import { reactive } from 'vue'
import type { DoorCloud } from '@/cloud'
import { authHeaders } from '@/auth'
import { BASE } from '@/base'

export interface DoorPhone {
  id: string
  name: string
  joined: number
  last_seen: number | null
  notifications: boolean
}

export const door = reactive({
  checked: false,
  away: false,          // reached through the printer's public name (role "away")
  role: null as 'home' | 'away' | null,   // null: no door answered (the panel, the house Wi-Fi page, dev)
  paired: false,
  phone: null as DoorPhone | null,
  actions: [] as string[],
})

/** Whether this screen may run an intent action. Everything is allowed at home. */
export function allowedHere(action: string): boolean {
  return !door.away || door.actions.includes(action)
}

/** The door's own words when it refuses something, or a fallback. */
async function message(r: Response, fallback: string): Promise<string> {
  try {
    const body = await r.json()
    return typeof body?.message === 'string' ? body.message : fallback
  } catch {
    return fallback
  }
}

export async function checkDoor(): Promise<void> {
  try {
    const r = await fetch(`${BASE}/door/me`, { credentials: 'include', cache: 'no-store', headers: authHeaders() })
    const d = r.ok ? await r.json() : null
    if (d) {
      // home: the printer's own name on the Wi-Fi, everything allowed (actions null); away: the short list
      door.role = d.role ?? (d.away ? 'away' : 'home')
      door.away = door.role === 'away'
      door.paired = !!d.paired
      door.phone = d.phone ?? null
      door.actions = Array.isArray(d.actions) ? d.actions : []
    }
  } catch {
    // no door here (home, the panel, a dev server): nothing changes
  } finally {
    door.checked = true
  }
}

/** Away: pair this browser with a code from the printer. Throws the door's message on failure. */
export async function pair(code: string, name: string): Promise<void> {
  const r = await fetch(`${BASE}/door/pair`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code: code.replace(/[^a-z0-9]/gi, '').toUpperCase(), name }),
  })
  if (!r.ok) throw new Error(await message(r, "That didn't work. Get a new code from the printer."))
  await checkDoor()
}

// ---- at the printer (home listener, through nginx) --------------------------------------

export interface PairCode {
  code: string
  url: string          // the printer's own pairing page (one printer, in the browser)
  shell_url?: string   // the Printers app's add page, which holds every printer: what the QR opens
  expires: number      // epoch seconds
}

export async function newPairCode(): Promise<PairCode> {
  const r = await fetch(`${BASE}/door/pair/new`, { method: 'POST' })
  if (!r.ok) throw new Error(await message(r, "Phones can't be added right now."))
  return r.json()
}

export async function listPhones(): Promise<DoorPhone[] | null> {
  try {
    const r = await fetch(`${BASE}/door/phones`, { cache: 'no-store', headers: authHeaders() })
    return r.ok ? ((await r.json()).phones ?? []) : null
  } catch {
    return null   // no door on this printer
  }
}

export async function removePhone(id: string): Promise<void> {
  const r = await fetch(`${BASE}/door/phones/${encodeURIComponent(id)}`, { method: 'DELETE', headers: authHeaders() })
  if (!r.ok && r.status !== 404) throw new Error(await message(r, "Couldn't remove that phone."))
}

/** Bench Cloud (docs/cloud.md): this printer in a house or not, and its last backup. Null: no door, or one without it. */
export async function doorCloud(): Promise<DoorCloud | null> {
  try {
    const r = await fetch(`${BASE}/door/cloud`, { cache: 'no-store', headers: authHeaders() })
    return r.ok ? await r.json() : null
  } catch {
    return null
  }
}

/** Puts this printer in the house, with a one-time join token from Bench Cloud. */
export async function joinCloud(joinToken: string, api: string): Promise<void> {
  const r = await fetch(`${BASE}/door/cloud/join`, {
    method: 'POST', headers: { ...authHeaders(), 'Content-Type': 'application/json' }, body: JSON.stringify({ join_token: joinToken, api }),
  })
  if (!r.ok) throw new Error(await message(r, "The printer couldn't join Bench Cloud. Try again."))
}

/** A starting name for this device, which the person can change. */
export function guessDeviceName(): string {
  const ua = navigator.userAgent
  if (/iPhone/.test(ua)) return 'iPhone'
  if (/iPad/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)) return 'iPad'
  if (/Pixel/.test(ua)) return 'Pixel'
  if (/Android/.test(ua)) return /Mobile/.test(ua) ? 'Android phone' : 'Android tablet'
  if (/Mac/.test(ua)) return 'Mac'
  if (/Windows/.test(ua)) return 'Windows PC'
  return 'This device'
}

/** What kind of device this is, for the printer's "wants to connect" card. */
export function guessDeviceKind(): 'phone' | 'tablet' | 'computer' {
  const ua = navigator.userAgent
  if (/iPad/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)) return 'tablet'
  if (/iPhone|Android.*Mobile/.test(ua)) return 'phone'
  if (/Android/.test(ua)) return 'tablet'
  return 'computer'
}
