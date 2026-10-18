// A new printer's first Wi-Fi, on its panel (docs/setup.md; design/setup/, direction C). Pure, so
// tests/wifi-setup.test.ts can pin which screen shows when; the service is setup/wifi_setup.py.

export type WifiMode = 'off' | 'looking' | 'open' | 'joining' | 'failed' | 'connected'
export type Security = 'open' | 'wpa' | 'sae' | 'enterprise'

export interface WifiNetwork {
  ssid: string
  signal: number          // 0-100
  security: Security
}

export interface WifiState {
  mode: WifiMode
  networks: WifiNetwork[]
  ssid: string | null     // the network it's joining, failed to join, or joined
  reason: 'password' | 'not_found' | 'timeout' | 'other' | null
  via: 'wifi' | 'cable' | null
  name: string | null     // what the printer is called, once chosen
  renaming: boolean       // that name is being applied (its name on the network changes)
  host: string            // its name on the network now (host.local)
  port: string            // the app's port
  setup?: { ssid: string; qr: string }   // the setup Wi-Fi, while it's open
}

export const OFF: WifiState = { mode: 'off', networks: [], ssid: null, reason: null, via: null, name: null, renaming: false, host: '', port: '' }

/** Where the person is on the panel, which the printer doesn't need to know. */
export type Here =
  | { at: 'start' }
  | { at: 'list' }
  | { at: 'type'; what: 'password' | 'ssid'; ssid?: string; hidden?: boolean }
  | { at: 'type'; what: 'name' }

export type Screen = 'looking' | 'start' | 'list' | 'keyboard' | 'wrong' | 'name' | 'done'

/** The panel's screen: the printer's step first, then where the person is within it. */
export function screenFor(s: WifiState, here: Here): Screen {
  const typing = here.at === 'type'
  switch (s.mode) {
    case 'looking': return 'looking'
    case 'open': return here.at === 'list' ? 'list' : typing && here.what !== 'name' ? 'keyboard' : 'start'
    case 'failed': return here.at === 'list' ? 'list' : typing && here.what !== 'name' ? 'keyboard' : 'wrong'
    case 'joining': return typing && here.what === 'name' ? 'keyboard' : 'name'
    case 'connected':
      if (typing && here.what === 'name') return 'keyboard'
      return s.name ? 'done' : 'name'
    default: return 'start'
  }
}

/** Which of Wi-Fi, Name, Phone the step bar lights. */
export function stepOf(screen: Screen, here: Here): 0 | 1 | 2 {
  if (screen === 'done') return 2
  if (screen === 'name' || (screen === 'keyboard' && here.at === 'type' && here.what === 'name')) return 1
  return 0
}

export const bars = (signal: number): 1 | 2 | 3 => (signal >= 67 ? 3 : signal >= 34 ? 2 : 1)

export const NAMES = ['Workshop', 'Studio', 'Desk', 'Garage', 'Office']

/** Its name on the network, as the installer makes it (elyir_bench.py hostname_for). */
export function hostnameFor(name: string): string {
  const h = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 63).replace(/-+$/, '')
  return h || 'printer'
}

/** The same check as the service, so the keyboard says so before the setup Wi-Fi closes. */
export function passwordProblem(password: string, security: Security): string | null {
  if (security === 'open') return null
  if (/^[0-9a-fA-F]{64}$/.test(password)) return null
  const n = new TextEncoder().encode(password).length
  return n >= 8 && n <= 63 ? null : 'Wi-Fi passwords are 8 to 63 characters.'
}

/** What went wrong, in the panel's words. */
export function wrongWords(s: WifiState): { headline: string; sub: string } {
  const n = s.ssid ?? 'That network'
  switch (s.reason) {
    case 'password':
      return { headline: `${n} didn't take that password.`, sub: "Scan again and retype it. The printer's setup Wi-Fi is back, so your phone can rejoin." }
    case 'not_found':
      return { headline: `The printer can't hear ${n}.`, sub: 'Check the name, or bring the printer closer to the router. Then scan again, or pick another network.' }
    default:
      return { headline: `${n} didn't answer.`, sub: 'Scan again to try once more. If it keeps happening, restart the router.' }
  }
}

/** Where a phone at home opens this printer when it has no door (no pairing): its own address. */
export function homeAddress(s: WifiState): string {
  const port = s.port && s.port !== '80' ? `:${s.port}` : ''
  return `http://${s.host.split('.')[0]}.local${port}/`
}
