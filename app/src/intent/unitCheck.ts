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

/** Measuring Happy Hare's gear (design/unit-setup/, "Gear calibration", C with B's mark): UnitCheck._gear_view. */
export type GearStepName = 'plan' | 'free' | 'mark' | 'ruler' | 'pad' | 'back' | 'encoder' | 'gates'

export interface GearCard {
  slot: number
  label: string
  state: 'ok' | 'now' | 'next' | 'skipped' | 'kept' | 'failed'
  line: string
  /** "98.5 for 100" under slot 1's By ruler */
  sub: string | null
}

export interface GearSheet {
  mm: number
  /** Past 80-120: it can't be the gear, so there's no Use */
  far: boolean
  title: string
  text: string
  note: string | null
  actions: IntentAction[]
}

export interface GearView {
  step: GearStepName
  /** per_slot: an encoder measures the other slots; one_gear: one gear drives them all; no_encoder: they keep the design value */
  kind: 'per_slot' | 'one_gear' | 'no_encoder'
  slots_n: number
  plan: { title: string; sub: string | null }[]
  side: { title: string; text: string } | null
  art: 'outlet' | 'one_gear'
  pushed: number
  push: number
  /** Pushes of 100 mm so far: the pad starts empty again after Measure again */
  tries: number
  mm: number | null
  range: [number, number]
  near: [number, number]
  sheet: GearSheet | null
  rows: { title: string; sub: string; tone: 'amber' | null }[] | null
  cards: GearCard[] | null
  progress: { seconds: number; elapsed: number | null; then: string } | null
  busy: boolean
}

/** The intent's unit_check (UnitCheck.view): null when no check is going. */
export interface UnitCheckView {
  unit: string
  unit_index: number
  driver: 'happy_hare' | 'afc'
  step: 'slots' | 'gear' | 'measure' | 'ready'
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
  gear?: GearView | null
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

/** The progress bar while measuring, and the words under it, from how long it's been going. Past a minute and a
 *  half it counts in minutes, "left" (the encoder's runs, board gc-encoder). */
export function progress(m: { seconds: number; elapsed: number | null }, extraSeconds = 0): { pct: number; words: string } {
  if (m.elapsed == null) return { pct: 0, words: m.seconds >= 90 ? `About ${Math.round(m.seconds / 60)} minutes` : `About ${m.seconds} seconds` }
  const done = m.elapsed + extraSeconds
  const pct = Math.max(0, Math.min(0.95, done / m.seconds))
  const left = m.seconds - done
  if (left <= 3) return { pct, words: 'Almost done' }
  if (left >= 90) return { pct, words: `About ${Math.round(left / 60)} minutes left` }
  return { pct, words: `About ${Math.max(5, Math.ceil(left / 5) * 5)} seconds` }
}

// ---- measuring the gear ------------------------------------------------------------------------------

export const GEAR_TYPED = 'unit_check_gear_measured'

/** A key on the number pad: digits, one decimal point with one digit after it, ⌫. Up to 999.9. */
export function padPress(value: string, key: string): string {
  if (key === '⌫') return value.slice(0, -1)
  if (key === '.') return value.includes('.') ? value : (value || '0') + '.'
  if (!/^[0-9]$/.test(key)) return value
  const [whole, frac] = value.split('.')
  if (frac !== undefined) return frac.length >= 1 ? value : value + key
  if (whole === '0') return key
  return whole.length >= 3 ? value : value + key
}

/** The number typed, or null while it isn't one yet. */
export function padNumber(value: string): number | null {
  if (!/^[0-9]+(\.[0-9])?$/.test(value)) return null
  const n = Number(value)
  return n > 0 ? n : null
}

/** The gear's buttons at the bottom right, quiet ones first. Stop is the back button, except while the encoder
 *  runs (board gc-encoder draws it). That's it carries the number typed, and waits for one. */
export function gearButtons(uc: UnitCheckView, typed: string): { action: IntentAction; disabled: boolean }[] {
  const g = uc.gear
  const running = !!g && (g.step === 'encoder' || g.step === 'gates') && uc.tone !== 'failed'
  const list = uc.actions.filter((a) => a.id !== 'unit_check_stop' || running)
  return [...list.filter((a) => !a.primary), ...list.filter((a) => a.primary)].map((a) => {
    if (a.id === 'unit_check_stop') return { action: a, disabled: false }
    if (a.id !== GEAR_TYPED) return { action: a, disabled: !!g?.busy }
    const mm = padNumber(typed)
    return { action: { ...a, args: { ...a.args, mm: mm ?? undefined } }, disabled: mm == null || !!g?.busy }
  })
}

/** Tube off, then the mark (board gb-mark): each item done (d), now (n) or to come. */
export function gearChecklist(g: GearView): { title: string; sub: string; state: 'd' | 'n' | '' }[] {
  const off = g.step !== 'free' || g.busy
  return [
    { title: 'Take the tube off the outlet', sub: 'Press the collar and pull.', state: off ? 'd' : 'n' },
    { title: "Draw a line right at the outlet's edge",
      sub: g.pushed ? 'Bench pushed a little out. Any marker that shows on it.' : 'Bench pushes a little out first.',
      state: g.step === 'mark' && !g.busy ? 'n' : '' },
  ]
}

/** Where the number sits against 90-110, for the dot on the range bar: 0 at the near range's low end, 1 at its high. */
export function rangeAt(g: Pick<GearView, 'near'>, mm: number | null): number | null {
  if (mm == null) return null
  return Math.max(0, Math.min(1, (mm - g.near[0]) / (g.near[1] - g.near[0])))
}

/** Care's Filament unit rows: one per unit Bench can check, and on Happy Hare one more to measure its gear. */
export function careRows(units: { name: string; check?: UnitCheckOffer | null; gear?: UnitCheckOffer | null }[] | undefined | null):
  { key: string; name: string; gear: boolean; line: string; action: IntentAction; why: string | null }[] {
  return (units ?? []).filter((u) => u.check).flatMap((u) => [
    {
      key: u.name, name: u.name, gear: false,
      line: u.check!.why ?? 'Check each slot, and measure the tube to the head. A few minutes at the printer.',
      action: u.check!.action,
      why: u.check!.why,
    },
    ...(u.gear ? [{
      key: `${u.name} gear`, name: u.name, gear: true,
      line: u.gear.why ?? 'Slot 1 with a ruler, then the unit measures the rest. A few minutes at the printer.',
      action: u.gear.action,
      why: u.gear.why,
    }] : []),
  ])
}
