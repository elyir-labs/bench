// The first Wi-Fi's state, followed on the panel only (App.vue): the service answers /wifi/state
// (setup/wifi_setup.py, docs/setup.md). No service (an older printer, a dev server) reads as off.

import { reactive } from 'vue'
import { OFF, type WifiState } from './wifi'

export const wifi = reactive({ checked: false, state: { ...OFF } as WifiState })

let timer = 0
let answered = false     // the service itself said so: off then means off
const GIVE_UP_MS = 5 * 60_000   // on a first boot the panel can load before the service runs (docs/image.md)
const started = Date.now()

export async function refreshWifi(): Promise<void> {
  try {
    const ctl = new AbortController()
    const t = window.setTimeout(() => ctl.abort(), 2500)
    const r = await fetch('/wifi/state', { cache: 'no-store', signal: ctl.signal })
    window.clearTimeout(t)
    // nginx without the service answers the app's index.html: that's off too
    const ok = r.ok && (r.headers.get('content-type') ?? '').includes('json')
    wifi.state = ok ? ((await r.json()) as WifiState) : { ...OFF }
    answered ||= ok
  } catch {
    // a blip (nginx reloading while the name is applied) keeps the last state; a first failure is off
    if (!wifi.checked) wifi.state = { ...OFF }
  }
  wifi.checked = true
  // set up (the service said off), or no service here at all after a while: nothing more to follow
  if (wifi.state.mode === 'off' && timer && (answered || Date.now() - started > GIVE_UP_MS)) {
    window.clearInterval(timer)
    timer = 0
  }
}

export function followWifi(): void {
  refreshWifi().then(() => {
    // a service that hasn't answered yet may still be starting: keep looking, more slowly
    if ((wifi.state.mode !== 'off' || !answered) && !timer) timer = window.setInterval(refreshWifi, answered ? 1500 : 3000)
  })
}

/** One of the steps: scan, join, name, done. Resolves with the service's message when it says no. */
export async function wifiAsk(what: 'scan' | 'join' | 'name' | 'done', body: object = {}): Promise<string | null> {
  try {
    const r = await fetch(`/wifi/${what}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
    const d = await r.json().catch(() => ({}))
    if (!r.ok) return typeof d?.message === 'string' ? d.message : "That didn't work. Try again."
    if (d?.mode) wifi.state = { ...wifi.state, ...d }   // move on at once; the next look fills in the rest
    return null
  } catch {
    return "The printer didn't answer. Try again."
  }
}
