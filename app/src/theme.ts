// Light or dark, set as html[data-theme] (tokens in styles/elyir-bench.css).
//
// The printer's own panel uses the theme stored on the printer (Moonraker database), so it
// survives kiosk restarts. The Bench Box has no Moonraker: its screen keeps the choice in the
// kiosk's own browser profile (keepPanelTheme). Any other screen, like a phone, keeps its own choice in this browser
// (Auto follows the OS) and never changes the panel's.
//   ?theme=light|dark     force a theme on this page (screenshots, demos)
//   ?screen=panel|phone   say which kind of screen this is; otherwise localhost is the panel
//   ?lite=1               no blur behind glass surfaces (a panel without a GPU)

import { computed, ref, watch } from 'vue'

export type Theme = 'light' | 'dark'
export type ScreenTheme = Theme | 'auto'
type Call = <T = any>(method: string, params?: Record<string, unknown>) => Promise<T>

const NAMESPACE = 'elyir-bench'
const KEY = 'panel_theme'
const CACHE = 'elyir-bench.panelTheme'
const SCREEN = 'elyir-bench.screenTheme'
const POLL_MS = 5000
const PAGE_COLOR: Record<Theme, string> = { dark: '#0b0e13', light: '#eceef2' }

const asTheme = (v: unknown): Theme | null => (v === 'light' || v === 'dark' ? v : null)

const query = new URLSearchParams(window.location.search)
const forced = asTheme(query.get('theme'))
const screen = query.get('screen')
export const isPanel = query.get('embed') === '1'   // inside the Printers app: a phone, never the panel
  ? false
  : screen
    ? screen === 'panel'
    : ['localhost', '127.0.0.1', '::1', '[::1]'].includes(window.location.hostname)

// ?lite=1: a panel drawn without a GPU (kiosk/start.sh, ELYIR_BENCH_RENDER=cpu). The router drops
// the query, so a reload after a renderer crash finds it in sessionStorage instead.
const LITE = 'elyir-bench.lite'
try {
  if (query.get('lite') === '1') sessionStorage.setItem(LITE, '1')
  if (sessionStorage.getItem(LITE) === '1') document.documentElement.dataset.lite = ''
} catch {
  if (query.get('lite') === '1') document.documentElement.dataset.lite = ''
}

function readCache(): Theme | null {
  try { return asTheme(localStorage.getItem(CACHE)) } catch { return null }
}
function writeCache(t: Theme) {
  try { localStorage.setItem(CACHE, t) } catch { /* private mode: the printer still has it */ }
}

const media = window.matchMedia('(prefers-color-scheme: light)')
const osTheme = ref<Theme>(media.matches ? 'light' : 'dark')
media.addEventListener('change', (e) => { osTheme.value = e.matches ? 'light' : 'dark' })

/** The printer panel's theme, as stored on the printer. Dark until told otherwise. */
export const panelTheme = ref<Theme>(readCache() ?? 'dark')

/** Any other screen's own choice, kept in this browser only. */
export const screenTheme = ref<ScreenTheme>((() => {
  try { return asTheme(localStorage.getItem(SCREEN)) ?? 'auto' } catch { return 'auto' }
})())
export function setScreenTheme(t: ScreenTheme) {
  screenTheme.value = t
  try {
    if (t === 'auto') localStorage.removeItem(SCREEN)
    else localStorage.setItem(SCREEN, t)
  } catch { /* private mode: lasts until the page closes */ }
}

export const theme = computed<Theme>(() => forced ?? (isPanel
  ? panelTheme.value
  : screenTheme.value === 'auto' ? osTheme.value : screenTheme.value))

watch(theme, (t) => {
  document.documentElement.dataset.theme = t
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', PAGE_COLOR[t])
}, { immediate: true })

function received(v: unknown) {
  const t = asTheme(v)
  if (!t) return
  panelTheme.value = t
  if (isPanel) writeCache(t)
}

/** Keep panelTheme in step with the printer, on the panel only (other screens never use it).
 *  Moonraker doesn't announce database writes, so an edit made elsewhere shows on the next
 *  poll. Returns a stop function. */
export function followPanelTheme(call: Call): () => void {
  if (!isPanel) return () => {}
  let pending = false
  const fetch = async () => {
    if (pending) return
    pending = true
    try {
      const r = await call<{ value?: unknown }>('server.database.get_item', { namespace: NAMESPACE, key: KEY })
      received(r?.value)
    } catch (e) {
      // Never chosen on this printer: store the default once, so the next polls find it
      // instead of Moonraker logging a "not found" error every few seconds.
      if (/not found/i.test((e as Error)?.message ?? '')) {
        await call('server.database.post_item', { namespace: NAMESPACE, key: KEY, value: panelTheme.value }).catch(() => undefined)
      }
      // otherwise not connected yet: keep what we have
    } finally {
      pending = false
    }
  }
  fetch()
  const timer = window.setInterval(fetch, POLL_MS)
  return () => window.clearInterval(timer)
}

export function keepPanelTheme(t: Theme): void {
  received(t)
}

export async function setPanelTheme(call: Call, t: Theme): Promise<void> {
  const before = panelTheme.value
  received(t)
  try {
    await call('server.database.post_item', { namespace: NAMESPACE, key: KEY, value: t })
  } catch (e) {
    received(before)
    throw e
  }
}
