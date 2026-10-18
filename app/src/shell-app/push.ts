// One notification subscription for every printer (docs/door.md, "One app for every printer").
//
// A browser allows one push subscription per service worker, so every printer has to sign this
// phone's pushes with the same key. The phone makes that P-256 key once, keeps it in IndexedDB,
// subscribes with its public half, and gives each printer the subscription and the key. A printer
// added later gets the same. Turning notifications off removes it from every printer.

import { get, put } from './db'
import { printers, type LivePrinter } from './printers'

export type PushState = 'insecure' | 'needs-install' | 'unsupported' | 'blocked' | 'off' | 'on' | 'partial'

interface VapidKey { publicKey: string; privateKey: string }

const isIOS = /iP(hone|ad|od)/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
const standalone = window.matchMedia('(display-mode: standalone)').matches || (navigator as { standalone?: boolean }).standalone === true
const supported = window.isSecureContext && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window

const b64u = (bytes: ArrayBuffer | Uint8Array) =>
  btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
const unb64u = (s: string) => {
  const raw = atob(s.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (s.length % 4)) % 4))
  const out = new Uint8Array(new ArrayBuffer(raw.length))
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i)
  return out
}

let registration: Promise<ServiceWorkerRegistration> | null = null
export function registerServiceWorker(): Promise<ServiceWorkerRegistration> | null {
  if (!supported) return null
  registration ??= navigator.serviceWorker.register('/sw.js', { scope: '/' }).then(() => navigator.serviceWorker.ready)
  return registration
}

/** This phone's signing key: made once, kept. */
async function vapidKey(): Promise<VapidKey> {
  const saved = await get<VapidKey>('kv', 'vapid')
  if (saved) return saved
  const pair = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true, ['sign'])
  const publicKey = b64u(await crypto.subtle.exportKey('raw', pair.publicKey))   // 65 bytes, uncompressed
  const jwk = await crypto.subtle.exportKey('jwk', pair.privateKey)
  const key = { publicKey, privateKey: jwk.d! }                                   // d: 32 bytes, base64url
  await put('kv', key, 'vapid')
  return key
}

function sameKey(sub: PushSubscription, key: Uint8Array): boolean {
  const k = sub.options.applicationServerKey
  if (!k) return false
  const a = new Uint8Array(k)
  return a.length === key.length && a.every((v, i) => v === key[i])
}

async function door(p: LivePrinter, path: string, init: RequestInit = {}): Promise<Response> {
  if (!p.base) throw new Error('not reachable')
  return fetch(`${p.base}/door/push/${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${p.token}` },
  })
}

/** Give one printer this phone's subscription and key. */
export async function subscribePrinter(p: LivePrinter): Promise<boolean> {
  if (!supported || Notification.permission !== 'granted' || !p.base) return false
  const reg = await registerServiceWorker()!
  const sub = await reg.pushManager.getSubscription()
  if (!sub) return false
  const r = await door(p, 'subscribe', {
    method: 'POST',
    body: JSON.stringify({ subscription: sub.toJSON(), tz: Intl.DateTimeFormat().resolvedOptions().timeZone, vapid: await vapidKey() }),
  }).catch(() => null)
  return !!r?.ok
}

export async function pushState(): Promise<{ state: PushState; printers: Record<string, boolean> }> {
  const each: Record<string, boolean> = {}
  if (!window.isSecureContext) return { state: 'insecure', printers: each }
  if (isIOS && !standalone) return { state: 'needs-install', printers: each }
  if (!supported) return { state: 'unsupported', printers: each }
  if (Notification.permission === 'denied') return { state: 'blocked', printers: each }
  const sub = await (await registerServiceWorker()!).pushManager.getSubscription()
  if (!sub) return { state: 'off', printers: each }
  await Promise.all(printers.map(async (p) => {
    const r = await door(p, 'me').catch(() => null)
    each[p.id] = !!(r?.ok && (await r.json()).subscribed)
  }))
  const reachable = printers.filter((p) => p.base)
  const on = reachable.filter((p) => each[p.id]).length
  return { state: on === 0 ? 'off' : on < reachable.length ? 'partial' : 'on', printers: each }
}

/** Call straight from a tap: iOS only asks for permission inside a user gesture. */
export async function enablePush(): Promise<void> {
  const asked = Notification.requestPermission()
  const reg = await registerServiceWorker()!
  if ((await asked) !== 'granted') return
  const key = await vapidKey()
  const pub = unb64u(key.publicKey)
  let sub = await reg.pushManager.getSubscription()
  if (sub && !sameKey(sub, pub)) {
    await sub.unsubscribe()
    sub = null
  }
  sub ??= await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: pub })
  await Promise.all(printers.filter((p) => p.base).map(subscribePrinter))
}

export async function disablePush(): Promise<void> {
  const reg = await registerServiceWorker()
  const sub = await reg?.pushManager.getSubscription()
  await Promise.all(printers.filter((p) => p.base).map((p) =>
    door(p, 'subscribe', { method: 'DELETE', body: JSON.stringify({ endpoint: sub?.endpoint ?? '' }) }).catch(() => null)))
  await sub?.unsubscribe()
}
