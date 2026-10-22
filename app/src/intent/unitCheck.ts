// Checking and measuring a Happy Hare or AFC unit (design/unit-setup/, B, stage 1, picked 22 October 2026): each
// slot's sensor and motor, then the tube to the head, then Ready. The printer runs it and words it
// (printer/unit_check.py); this is what the flow draws from that, and where it's offered.
//
// Pure, so tests/unit-check.test.ts can pin it; the flow, Materials and Care use it.
import type { IntentAction } from './types'

export interface UnitCheckCard {
  slot: number
  label: string
  state: 'next' | 'waiting' | 'testing' | 'ok' | 'skipped' | 'failed'
  sensor: boolean | null
  motor: boolean | null
  line: string | null
}

export interface UnitCheckMeasure {
  what: 'tube' | 'slot'
  slot: number
  /** Roughly how long it takes, and how long it's been going (null while it waits on a person). */
  seconds: number
  elapsed: number | null
  n: number
  of: number
  note: string
}

/** The intent's unit_check (UnitCheck.view): null when no check is going. */
export interface UnitCheckView {
  unit: string
  unit_index: number
  driver: 'happy_hare' | 'afc'
  step: 'slots' | 'measure' | 'ready'
  n: number
  of: number
  /** "Set up a filament unit" when the check is steps 4 and 5 of setting the unit up (unit-setup stage 2) */
  title?: string | null
  headline: string
  detail: string | null
  /** The detail is about the slot before: it passed (ok) or didn't (failed). */
  tone: 'ok' | 'failed' | null
  slots: UnitCheckCard[]
  current: number | null
  /** "2 of 8 checked. Then Bench measures the tube to the head." */
  note: string | null
  measure: UnitCheckMeasure | null
  ready: { rows: { title: string; sub: string }[] } | null
  stopping: boolean
  actions: IntentAction[]
  raw: string
}

/** Check and measure on one unit: the action, and why it can't run right now (null when it can). */
export interface UnitCheckOffer { action: IntentAction; why: string | null }

export const FLOW_TITLE = 'Check and measure'

/** The flow takes the screen while a check is going, at home: it needs hands at the unit. */
export function flowShown(uc: UnitCheckView | null | undefined, away: boolean): boolean {
  return !!uc && !away
}

/** "1 of 3", "2 of 3", "Done", beside the dots. */
export function stepLabel(uc: UnitCheckView): string {
  return uc.step === 'ready' ? 'Done' : `${uc.n} of ${uc.of}`
}

/** One per step: d done, n now. */
export function dots(uc: UnitCheckView): ('d' | 'n' | '')[] {
  return Array.from({ length: uc.of }, (_, i) => (uc.step === 'ready' || i < uc.n - 1 ? 'd' : i === uc.n - 1 ? 'n' : ''))
}

/** The back button: stops the check (after the command running now), or closes Ready. */
export function backAction(uc: UnitCheckView): IntentAction | null {
  if (uc.stopping) return null
  return uc.actions.find((a) => a.id === (uc.step === 'ready' ? 'unit_check_done' : 'unit_check_stop')) ?? null
}

/** The buttons at the bottom right, quiet ones first and the main one last. Stop is the back button while slots
 *  are checked; while measuring it's drawn as a button too (board a-measure). */
export function barButtons(uc: UnitCheckView): IntentAction[] {
  const measuring = uc.step === 'measure' && !uc.actions.some((a) => a.id === 'unit_check_retry' || a.id === 'unit_check_skip')
  const list = uc.actions.filter((a) => a.id !== 'unit_check_stop' || measuring)
  return [...list.filter((a) => !a.primary), ...list.filter((a) => a.primary)]
}

/** A card's lines under "Slot 3": ✓ Sensor, ✓ Motor, or what it's waiting on. */
export function cardLines(c: UnitCheckCard): { mark: 'y' | 'q' | 'spin' | null; text: string }[] {
  if (c.state === 'ok') return [{ mark: 'y', text: 'Sensor' }, { mark: 'y', text: 'Motor' }]
  if (c.state === 'failed') {
    return [...(c.sensor ? [{ mark: 'y' as const, text: 'Sensor' }] : []), { mark: 'q', text: c.line ?? "Didn't pass" }]
  }
  if (c.state === 'waiting' || c.state === 'testing') return [{ mark: 'spin', text: c.line ?? '' }]
  return [{ mark: null, text: c.line ?? '' }]
}

/** The progress bar while measuring, and the words under it, from how long it's been going. */
export function progress(m: UnitCheckMeasure, extraSeconds = 0): { pct: number; words: string } {
  if (m.elapsed == null) return { pct: 0, words: `About ${m.seconds} seconds` }
  const done = m.elapsed + extraSeconds
  const pct = Math.max(0, Math.min(0.95, done / m.seconds))
  const left = m.seconds - done
  if (left <= 3) return { pct, words: 'Almost done' }
  return { pct, words: `About ${Math.max(5, Math.ceil(left / 5) * 5)} seconds` }
}

/** Care's Filament unit row: one per unit Bench can check. */
export function careRows(units: { name: string; check?: UnitCheckOffer | null }[] | undefined | null):
  { name: string; line: string; action: IntentAction; why: string | null }[] {
  return (units ?? []).filter((u) => u.check).map((u) => ({
    name: u.name,
    line: u.check!.why ?? 'Check each slot, and measure the tube to the head. A few minutes at the printer.',
    action: u.check!.action,
    why: u.check!.why,
  }))
}
