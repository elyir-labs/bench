// The one object every screen renders. Mirrors elyir_bench_intent.py exactly.

import type { CareSummary } from './care'
import type { PowerView } from './power'
import type { LightView } from './light'
import type { HandsView } from './hands'

// setup: Klipper has no printer.cfg yet, a fresh card (docs/bring-it-over.md): Now the printer itself, never Problem
export type IntentState = 'ready' | 'preparing' | 'printing' | 'needs_you' | 'finished' | 'problem' | 'setup'

export type ActionStyle = 'default' | 'accent' | 'amber' | 'green' | 'red'

export interface IntentAction {
  id: string
  label: string
  primary: boolean
  style: ActionStyle
  args?: Record<string, unknown>
  /** Ends a print (or is the emergency stop): press and hold, never a single tap (components/now/HoldButton.vue). */
  hold?: boolean
}

export interface IntentStep {
  id: string
  label: string
  status: 'done' | 'now' | 'todo'
  /** A step a person does (changing filament: pull, push, check). */
  you?: boolean
  /** A second line under the step running now, e.g. "Mapping the bed". */
  detail?: string
}

/** What the picture in the ring is drawn from (design/now-illustrated/, A). The printer's own numbers. */
export interface IntentArt {
  /** While getting ready: the drawing for the step PRINT_START is on. */
  stage: 'warming' | 'soaking' | 'home' | 'level' | 'mesh' | 'heating' | 'prime' | null
  /** The head over the bed, while homing, levelling, meshing or priming: x and y 0..1 from the
   *  axes' minimum (y 0 is the front), z in mm. */
  head: [number, number, number] | null
  /** The last levelling pass, mm. */
  level: { range: number; tolerance: number } | null
  /** Mesh cells the head has been over: bit j*n+i, j counted from the front. */
  mesh: { n: number; seen: number } | null
  /** How far up the object is, 0..1, by layer (or Z over the object's height). */
  built: number | null
}

/** Warming up before a print; `options` answer "What are you printing next?" while the printer is free. */
export interface IntentWarm {
  active: boolean
  material?: string
  /** Reached the bed (and chamber) temperature; staying warm until `until`. */
  warm?: boolean
  bed?: { temperature: number; target: number }
  chamber?: { temperature: number; target: number } | null
  /** Rough minutes left while warming. */
  minutes?: number | null
  until?: string | null
  /** warm_up actions, one per loaded material; args.note says which spools. */
  options?: IntentAction[]
}

/** First layer: squish more, squish less (design/first-layer/, B). Amounts in mm, + is further from the bed. */
export interface FirstLayerAmount { z: number; words: string; mm: string }
export interface IntentFirstLayer {
  /** The printer keeps values ([save_variables]); without it nudges still work but nothing is kept. */
  can_keep: boolean
  /** Layers 1 to 3 of a print: Further / Closer (squish_less / squish_more), and where it is now. */
  adjust: { total: number; words: string; mm: string; moved: number; actions: IntentAction[] } | null
  /** At the end, when this print was nudged: "Keep the new first layer for next time?" */
  keep: { moved: number; total: number; headline: string; detail: string; actions: IntentAction[] } | null
  /** What's kept, for Care; `used` is false when it was kept against the other way of finding Z. */
  kept: (FirstLayerAmount & { against: 'scan' | 'tap' | null; used: boolean; at: string | null;
          back: FirstLayerAmount | null; actions: IntentAction[] }) | null
  /** The way of finding Z changed (scan to tap): asked once, on Ready. */
  ask: { headline: string; detail: string; actions: IntentAction[] } | null
}

/** A filament as the change routine knows it. */
export interface ChangeFilament { color: string | null; material: string | null; name: string | null }

/** Changing filament by hand, the check after a swap, swapping the spool in a slot (design/slots/), or switching
 *  colour mid-print on a printer with a unit (design/colour-change/: 'colour'). */
export interface IntentChange {
  kind: 'change' | 'unload' | 'load' | 'ace' | 'slot' | 'colour'
  /** A colour switch: to a loaded spool, a new spool put in an empty slot first, or a full slot's spool swapped first. */
  flow?: 'switch' | 'put' | 'swap'
  /** A colour switch the Print sheet planned: nobody's needed, so no check. */
  auto?: boolean
  /** What the ring's pill says instead of "Step n of m" ("Layer 56 of 140"). */
  pill?: string | null
  /** Said before the detail where the camera is shown: the check is done by eye on it. */
  look?: string | null
  step: string
  /** The head, drawn: warming, taking out, pull, push, purging, done. For a slot, the unit: back, insert. */
  art: 'still' | 'heat' | 'out' | 'pull' | 'push' | 'purge' | 'done' | 'back' | 'insert'
  /** Swapping a spool: which slot. */
  slot?: number
  out: ChangeFilament | null
  in: ChangeFilament | null
  /** Step n of `of`. */
  n: number
  of: number
  /** Waiting on a person. */
  you: boolean
  /** "What is it?" hasn't been answered yet. */
  ask: boolean
  /** One-tap answers to "What is it?"; primary marks the one picked. */
  choices: IntentAction[]
}

/** One slot at a colour-change pause (design/colour-change/, A): what tapping it would do, in words. */
export interface ColourTile {
  slot: number
  color: string | null
  status: 'ready' | 'empty' | 'low' | 'unknown'
  in_use: boolean
  /** "White", "Empty". */
  word: string
  /** "PLA", "in the head", "PLA, low", "put one in". */
  sub: string
  /** How the second line is coloured: the head's blue, or amber for low or another material. */
  tone: 'accent' | 'amber' | null
  how: 'keep' | 'switch' | 'put_in' | 'swap' | null
  /** The amber button when this tile is picked. */
  action: IntentAction | null
  /** The line under the tiles: [bold, the rest]. */
  says: [string, string] | null
  /** The same, on a phone away from home. */
  says_away: [string, string] | null
  /** "Or put a different spool in slot 2": swap a full slot (only once the unit is known to do it). */
  link: IntentAction | null
  /** Another material than the print's: asked once, never refused. The action then carries sure. */
  ask: { text: string; label: string } | null
  /** Away from home a switch is confirmed once more; the action then carries away_ok. */
  confirm_away: { text: string; label: string } | null
  /** Needs hands: not offered away. */
  at_printer: boolean
  why: string | null
}

/** The colour-change pause on a printer with a unit, and why it's a pause. */
export interface IntentColour {
  reason: 'not_planned' | 'not_loaded' | 'asked' | 'not_switched' | 'plan_gone'
  n: number
  layer: number | null
  color: string | null
  material: string | null
  /** "The file asks for white." (said on a phone, where the tiles' line is shorter) */
  asks: string | null
  /** The slot picked to begin with: the file's colour, else what's in the head. */
  picked: number | null
  units: { name: string; slots: number[] }[]
  slots: ColourTile[]
  /** "Slots 7 and 8 are empty. Putting a spool in needs someone at the printer." */
  away_note: string | null
}

/** The Print sheet's plan for a file with colour changes on a printer with a unit (design/colour-change/, C). */
export interface ColourSheet {
  headline: string
  detail: string
  material: string | null
  start: { slot: number | null; name: string; color: string | null; loaded: boolean; line: string }
  changes: {
    n: number; layer: number | null; color: string | null; label: string
    /** The loaded spool that matches the file's colour and the print's material. */
    slot: number | null
    not_loaded: boolean
    named_line: string | null
    missing_line: string | null
    pause_line: string
  }[]
  choices: { slot: number; name: string; color: string | null; material: string | null; line: string; differs: boolean; ask: string | null }[]
  labels: { start: string; pause: string; print: string; back: string; change: string; yes: string }
}

export interface IntentJob {
  name: string
  filename: string
  thumbnail: string | null
  grams: number | null
  state: string
  progress: number
  layer: number | null
  layers: number | null
  elapsed_s: number
  total_s: number
  remaining_s: number | null
  eta: string | null
  eta_clock: string | null
  estimated_s: number | null
  colors: string[]
  material: string | null
}

/** Before a print: does the file's filament match what's loaded? (check_print) */
export interface PrintCheck {
  ok: boolean
  filename: string
  missing: { color: string | null; material: string | null }[]
  headline?: string
  short?: string
  detail?: string
  actions?: IntentAction[]
  /** One spool and the printer isn't sure what's on it: the sheet asks rather than warns. */
  ask?: boolean
  /** Per filament the file uses, where it comes from: "Blue PLA is loaded, slot 4". Loaded is
   *  null when there's nothing to tell it by. Absent from an intent layer older than the library. */
  uses?: { color: string | null; material: string | null; loaded: boolean | null; slot: number | null; line: string }[]
  /** The file changes colour (M600) and the printer has a unit: the sheet plans each change (design/colour-change/, C). */
  colour?: ColourSheet
  colour_changes?: { layer: number | null; color: string | null; slot: number | null; not_loaded: boolean }[]
}

export interface IntentSpool {
  slot: number
  /** "Orange PETG": colour and material in words, from the intent layer. Null when unknown. */
  name?: string | null
  /** What tapping this spool can do right now (load / switch / unload); empty while busy. */
  actions?: IntentAction[]
  /** One line about what the action does, e.g. "Heats the nozzle, feeds it in. About 2 minutes." */
  note?: string | null
  /** The quiet correction when the printer's memory is wrong; nothing moves. */
  fix?: IntentAction | null
  color: string | null
  material: string | null
  grams: number | null
  status: 'ready' | 'empty' | 'low' | 'unknown'
  in_use: boolean
  rfid: boolean
  /** A printer without a filament unit: its one spool, which the printer can't read. */
  direct?: boolean
  /** Where a direct spool's colour and material come from. */
  source?: 'spoolman' | 'told' | 'guess' | 'unknown'
  /** When it was said or guessed. */
  since?: string | null
  /** Filament left the head and came back since: it may be a different spool now. */
  changed?: boolean
  /** What was on before the change. */
  was?: { name: string | null; color: string | null; material: string | null } | null
  /** The print a guess came from, by name. */
  guess_from?: string | null
  /** Spools that were on before, newest first: quick answers to "New filament?". */
  recent?: { name: string | null; color: string | null; material: string | null }[]
  /** Move filament (push in / pull back) is offered for this slot right now. */
  move?: boolean
  /** With carry-on on: this spool stands by for that slot (its card says "spare"). */
  spare_for?: number | null
  /** "If it runs out mid-print, the White PLA in slot 6 carries on." */
  spare_note?: string | null
  /** The slot in the head: whether the unit pushes along while printing (feed assist). */
  assist?: boolean | null
}

/** How long and how warm a unit's dryer would run, from what's inside it. */
export interface DryPlan { temp: number; hours: number; why: string; hours_why: string; materials: string[]; names: string[] }

/** One filament unit (design/slots/, B): its slots, its temperature and its dryer. */
export interface IntentUnit {
  index: number
  name: string
  slots: number[]
  connected: boolean
  temp: number | null
  drying: { target: number; minutes_left: number; minutes_total: number; ends_clock: string } | null
  dry: DryPlan
  /** dry_unit (args unit, hours) or stop_drying. */
  actions: IntentAction[]
}

/** A labelled part of the print (design/skip-objects/, A): Klipper's [exclude_object], numbered the way a person
 *  sees the bed from the front. name is Klipper's, for the skip_part action. */
export interface IntentPart {
  name: string
  n: number
  label: string
  where: string
  center: number[]
  polygon: number[][]
  state: 'printing' | 'waiting' | 'skipped'
}
export interface IntentParts {
  items: IntentPart[]
  total: number
  left: number
  skipped: string[]
  bed: number[]            // [x0, y0, x1, y1] in mm
  can_skip: boolean
}

export interface OutageView {
  back: boolean
  held: 'print' | 'paused'
  minutes: number
  battery: number | null
  runtime_min: number | null
  bed: number | null
  layer: number | null
  heating: boolean
  to: number | null
  /** seconds until it heats up to carry on, while the power settles */
  carry_in: number | null
}

export interface LostView {
  file: string
  name: string
  layer: number | null
  layers: number | null
  /** the height it reached, mm, counted from the plate */
  z: number | null
  height: number | null
  pct: number
  material: string | null
  off_at: string
  back_at: string
  /** it was holding on a battery first */
  held: boolean
  /** the plate's objects not skipped (p0c1__name), to know how many of each part are left */
  objects: string[]
}

export interface Intent {
  version: number
  state: IntentState
  phase: string
  since: string
  headline: string
  detail: string
  safe: boolean
  expires: string | null
  actions: IntentAction[]
  steps: IntentStep[]
  job: IntentJob | null
  art?: IntentArt | null
  change?: IntentChange | null
  /** Paused at a colour change on a printer with a unit (design/colour-change/, A). */
  colour?: IntentColour | null
  warm?: IntentWarm | null
  first_layer?: IntentFirstLayer | null
  parts?: IntentParts | null
  spools: IntentSpool[]
  /** Filament units plugged in vs picked up; notice says what to do when one is missing. */
  /** What's in the head, and whether the sensor and the printer's memory disagree. */
  care?: CareSummary | null   // maintenance the printer counts itself (see ./care.ts)
  /** Turn off / Restart (design/power/): offered or why not, and the wait while it cools (see ./power.ts). */
  power?: PowerView | null
  /** A print held on a UPS's battery, or carrying on once the power is back (design/power-loss/, A). */
  outage?: OutageView | null
  /** A print the power took, on Ready: where it got to (design/power-loss/, A). */
  lost?: LostView | null
  /** Move and heat by hand (design/hands-on/, C): offered or why not, where the head is, what a job holds (see ./hands.ts). */
  hands?: HandsView | null
  /** The chamber light (design/chamber-light/, A): null when the printer has none (see ./light.ts). */
  light?: LightView | null
  head?: {
    loaded: boolean | null
    slot: number | null
    mismatch: 'unknown_spool' | 'phantom_spool' | null
    notice: { headline: string; detail: string } | null
    actions: IntentAction[]
    choices: IntentAction[]
  }
  units?: {
    present: number | null
    known: number
    missing: number
    notice: { headline: string; detail: string } | null
    actions: IntentAction[]
    /** Each unit, in slot order (absent from an intent layer older than design/slots/). */
    list?: IntentUnit[]
    /** Carry on with a matching spool when one runs out; null when the unit can't. */
    carry_on?: boolean | null
  } | null
  /** An untagged spool was pushed into an empty slot: "New spool in slot 7. What is it?" */
  new_spool?: { slot: number; headline: string; detail: string; choices: IntentAction[] } | null
  /** The unit carried on with a matching spool by itself, mid-print. */
  carried?: { from: number; to: number; pct: number; headline: string; detail: string; actions: IntentAction[]; kind?: 'colour' } | null
  /** Finish setting up (docs/setup-card.md): the phone shows the card while open. */
  setup?: { open: boolean } | null
  printer: {
    name: string
    connected: boolean
    bed: { temperature: number; target: number }
    nozzle: { temperature: number; target: number }
    chamber: { temperature: number } | null
    advanced_url?: string
    screen_switch?: boolean   // the printer's screen can show KlipperScreen instead (Care)
    screen_switch_failed?: string | null   // the last switch didn't come up and was undone: what happened
    /** The printer's screen is on trial after the setup card's Try it (docs/setup-card.md): the panel asks Keep? */
    screen_trial?: { seconds_left: number } | null
    simulated?: boolean
    scenario?: string
  }
  raw: string
  now: string
}

export interface HistoryJob {
  job_id: string
  filename: string
  status: string
  start_time: number
  end_time: number
  print_duration: number
  filament_used: number
  metadata?: Record<string, any>
}
