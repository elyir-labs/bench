// Phone notifications. The door (same origin, /door/push/*) owns pairing, keys and sending;
// this file registers the service worker and keeps this browser's subscription in step with
// the switch in Care. In dev, tools/push-dev.py stands in for the door.

import { BASE } from '@/base'

export type PushStatus =
  | 'insecure'       // plain http, e.g. http://workshop.local: browsers refuse push here
  | 'needs-install'  // iPhone or iPad in Safari: push works only from the Home Screen app
  | 'unsupported'    // this browser has no push at all
  | 'no-door'        // the printer has nothing to send with yet
  | 'blocked'        // notifications were refused for this site
  | 'off'
  | 'on'

const isIOS = /iP(hone|ad|od)/.test(navigator.userAgent)
  || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)   // iPadOS reports as a Mac
const standalone = window.matchMedia('(display-mode: standalone)').matches
  || (navigator as { standalone?: boolean }).standalone === true

// through a Bench Box the root is the box's: no service worker of a printer's there
const supported = !BASE && window.isSecureContext && 'serviceWorker' in navigator
  && 'PushManager' in window && 'Notification' in window

let registration: Promise<ServiceWorkerRegistration> | null = null

/** Register /sw.js once, where push can work at all. Safe to call repeatedly. */
export function registerServiceWorker(): Promise<ServiceWorkerRegistration> | null {
  if (!supported) return null
  registration ??= navigator.serviceWorker.register('/sw.js', { scope: '/' })
    .then(() => navigator.serviceWorker.ready)
  return registration
}

class DoorError extends Error {
  constructor(public status: number) { super(`door answered ${status}`) }
}

async function door<T = unknown>(path: string, init: RequestInit = {}): Promise<T | null> {
  const r = await fetch(`${BASE}/door/push/${path}`, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!r.ok) throw new DoorError(r.status)
  return r.status === 204 ? null : (await r.json()) as T
}

function keyBytes(b64url: string): Uint8Array<ArrayBuffer> {
  const b64 = b64url.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (b64url.length % 4)) % 4)
  const raw = atob(b64)
  const out = new Uint8Array(new ArrayBuffer(raw.length))
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i)
  return out
}

function sameKey(sub: PushSubscription, key: Uint8Array): boolean {
  const k = sub.options.applicationServerKey
  if (!k) return false
  const a = new Uint8Array(k)
  return a.length === key.length && a.every((v, i) => v === key[i])
}

export async function pushStatus(): Promise<PushStatus> {
  if (!window.isSecureContext) return 'insecure'
  if (isIOS && !standalone) return 'needs-install'
  if (!supported) return 'unsupported'
  if (Notification.permission === 'denied') return 'blocked'
  let me: { subscribed: boolean } | null
  try {
    me = await door<{ subscribed: boolean }>('me')
  } catch {
    return 'no-door'
  }
  const sub = await (await registerServiceWorker()!).pushManager.getSubscription()
  return me?.subscribed && sub ? 'on' : 'off'
}

/** Call straight from a tap: iOS only asks for permission inside a user gesture. */
export async function enablePush(): Promise<PushStatus> {
  const asked = Notification.requestPermission()
  const reg = await registerServiceWorker()!
  const permission = await asked
  if (permission !== 'granted') return permission === 'denied' ? 'blocked' : 'off'

  const res = await door<{ publicKey: string }>('key')
  const key = keyBytes(res!.publicKey)
  let sub = await reg.pushManager.getSubscription()
  if (sub && !sameKey(sub, key)) {   // the printer's keys changed: start over
    await sub.unsubscribe()
    sub = null
  }
  sub ??= await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key })
  await door('subscribe', { method: 'POST', body: JSON.stringify({ subscription: sub.toJSON() }) })
  return 'on'
}

export async function disablePush(): Promise<PushStatus> {
  const reg = await registerServiceWorker()
  const sub = await reg?.pushManager.getSubscription()
  if (sub) {
    await door('subscribe', { method: 'DELETE', body: JSON.stringify({ endpoint: sub.endpoint }) }).catch(() => undefined)
    await sub.unsubscribe()
  }
  return 'off'
}
