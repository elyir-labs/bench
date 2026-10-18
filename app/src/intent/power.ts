// Turning the printer off (design/power/, A, picked 5 October 2026). The printer runs the wait (the intent
// layer's turning_off / restarting phases); this is the words around it: the sheet that asks, and what a phone
// says once the printer is gone.
//
// Pure, so tests/power.test.ts can pin it; Care, the sheet and Now use it.

export type PowerKind = 'off' | 'restart'

/** The intent's power view (printer/elyir_bench_intent.py, IntentTracker._power_view). */
export interface PowerView {
  allowed: boolean
  why: string | null
  cool_to: number
  kind: PowerKind | null
  going?: boolean
  failed?: boolean
  progress?: number
  nozzle?: number
}

export interface SheetWords { title: string; body: string; note: string | null; confirm: string }

/** About how long the nozzle takes to drop to the fan's temperature with the fan on. */
export function coolMinutes(nozzle: number, coolTo: number): number {
  return nozzle > coolTo ? Math.max(1, Math.round((nozzle - coolTo) / 45)) : 0
}

/** The sheet Care's Turn off and Restart open. `atPrinter`: the printer's own screen. */
export function sheetWords(kind: PowerKind, name: string, nozzle: number, coolTo: number, atPrinter: boolean): SheetWords {
  const off = kind === 'off'
  const mins = coolMinutes(nozzle, coolTo)
  const then = off ? 'When its screen goes dark, switch it off.' : "Then it restarts, and it's back in about a minute."
  const body = mins
    ? `The nozzle is ${Math.round(nozzle)}°. ${name} lets it cool first, about ${mins} minute${mins === 1 ? '' : 's'}, so its fan keeps the hot end clear. ${then}`
    : off ? `${name} turns off in a few seconds. ${then}` : `${name} restarts now, and it's back in about a minute.`
  return {
    title: off ? `Turn off ${name}?` : `Restart ${name}?`,
    body,
    note: off && !atPrinter ? 'It can only be switched on again at the printer.' : null,
    confirm: off ? 'Turn off' : 'Restart',
  }
}

/** What this browser saw: the printer going off or restarting, kept so the page can say so after it's gone. */
export interface PowerMemo { name: string; kind: PowerKind; at: number }

export interface Gone { kind: 'off' | 'restarting' | 'unreachable'; headline: string; detail: string }

/** A restart that isn't back after this long is no longer "restarting". */
export const RESTART_GRACE_S = 3 * 60
/** Connection lost this long, with no reason known: say so instead of showing the last state. */
export const UNREACHABLE_AFTER_S = 15

const clock = (t: number) => new Date(t * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }).toLowerCase()

/** What Now says when the printer doesn't answer, or null to keep showing the last state (a short blip). */
export function goneView(o: { connected: boolean; name: string; memo: PowerMemo | null; lostFor: number; now: number }): Gone | null {
  if (o.connected) return null
  const name = o.memo?.name || o.name || 'The printer'
  if (o.memo?.kind === 'off') {
    return { kind: 'off', headline: `${name} is off`, detail: `Turned off at ${clock(o.memo.at)}. Switch it on at the printer, and this page finds it again.` }
  }
  if (o.memo?.kind === 'restart' && o.now - o.memo.at < RESTART_GRACE_S) {
    return { kind: 'restarting', headline: 'Restarting', detail: `${name} is back in about a minute.` }
  }
  if (o.lostFor >= UNREACHABLE_AFTER_S) {
    return { kind: 'unreachable', headline: `Can't reach ${o.memo?.name || o.name || 'the printer'}`, detail: "It may be switched off, or off the Wi-Fi. This page keeps trying." }
  }
  return null
}

/** The memo to keep, given the latest intent's power view: set when it starts going, cleared once it's back. */
export function nextMemo(memo: PowerMemo | null, power: PowerView | null | undefined, name: string, now: number): PowerMemo | null {
  if (power?.going && power.kind) return memo?.kind === power.kind ? memo : { name, kind: power.kind, at: now }
  return null
}
