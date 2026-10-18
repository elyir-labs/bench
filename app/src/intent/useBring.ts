// Bring it over, followed: GET /printer/intent/bring (printer.intent.bring), asked when the printer's state changes
// and again every second while it works, every few while the screens show (bring.ts says when). The screens
// (components/bring/BringScreen.vue) and App.vue read `bring`; the Wi-Fi's Connected link opens it with openBring.

import { computed, reactive, watch } from 'vue'
import { EMPTY, pollMs, resultKey, shown, type BringInfo, type Here } from './bring.ts'
import type { useIntentStore } from './store'

type Store = ReturnType<typeof useIntentStore>

const SEEN = 'elyir-bench.bring.seen'
const readSeen = () => { try { return localStorage.getItem(SEEN) ?? '' } catch { return '' } }

export const bring = reactive({
  info: null as BringInfo | null,
  /** Opened from the Wi-Fi's Connected link, on a printer whose state isn't setup (yet). */
  requested: false,
  here: { at: 'start' } as Here,
  /** Bring it over was pressed on this screen: its result shows here even if an older one was seen. */
  inFlow: false,
  seenKey: readSeen(),
})

/** This screen has already said how the last bring ended. */
export const seen = computed(() => !bring.inFlow && !!bring.info?.result && bring.seenKey === resultKey(bring.info))

/** Shown instead of the app (bring.ts shown()). */
export const bringShownFor = (state: string | null | undefined) =>
  shown({ state, info: bring.info, requested: bring.requested, seen: seen.value })

export async function refreshBring(store: Store): Promise<void> {
  if (!store.connected) return
  try {
    bring.info = { ...EMPTY, ...(await store.call<BringInfo>('printer.intent.bring')) }
  } catch {
    // a printer without Bring it over, or Moonraker restarting mid-copy: keep what was last said
  }
}

/** Ask again on connecting, on each change of the printer's state, and on a timer while it matters. */
let following: (() => void) | null = null
let kick: () => void = () => {}
export function followBring(store: Store): () => void {
  if (following) return following   // App.vue starts it with the intent store, which may start twice
  let timer = 0
  let gen = 0   // a newer ask replaces the timer an older one would set
  const tick = async () => {
    window.clearTimeout(timer)
    const mine = ++gen
    await refreshBring(store)
    if (mine !== gen) return
    const ms = pollMs(bring.info, bringShownFor(store.intent?.state))
    if (ms) timer = window.setTimeout(tick, ms)
  }
  kick = () => { tick() }
  const stop = watch(() => [store.connected, store.intent?.state, bring.requested].join('|'), tick, { immediate: true })
  following = () => { stop(); window.clearTimeout(timer); following = null; kick = () => {} }
  return following
}

/** One of bring_scan, bring_plan, bring_address, bring_apply; then what the printer says now. */
export async function bringAct(store: Store, action: string, args: Record<string, unknown> = {}): Promise<string | null> {
  await store.act(action, args)
  const err = store.actionError
  kick()   // asks now, then every second while the printer works on it
  return err
}

/** The Wi-Fi's Connected link, after Wi-Fi setup has ended: straight to the sources. */
export function openBring(): void {
  bring.requested = true
  bring.here = { at: 'sources' }
}

/** Done: this screen has seen how it ended; the printer's normal Now from here. */
export function finishBring(): void {
  bring.seenKey = resultKey(bring.info)
  try { localStorage.setItem(SEEN, bring.seenKey) } catch { /* private mode: said again next time */ }
  bring.inFlow = false
  bring.requested = false
  bring.here = { at: 'start' }
}
