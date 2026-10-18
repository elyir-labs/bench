// Finish setting up (design/getting-started/, C "Ready first", picked 5 October 2026; the contract with the
// printer's side is docs/setup-card.md). One card under Ready on a phone offers what's left after the install
// command, a row at a time: notifications for this phone, the printer's screen, what works on this printer.
// The words and the rules for which rows show live here, pure, so tests/setup-card.test.ts can pin them to the
// boards; SetupCard.vue, WorksSheet.vue, IncludeSheet.vue and TrialBar.vue only draw them.

import type { PushStatus } from '../push'

/** The product's name in what a person reads (the public copy says Elyir Bench). */
export const PRODUCT = 'Elyir Bench'

export type SetupRowId = 'notify' | 'screen' | 'works'
export type ScreenState = 'offer' | 'fetching' | 'trial' | 'done' | 'kept_klipperscreen' | 'cant'
export type IncludeState = 'off' | 'on' | 'adding' | 'removing' | 'failed'
export type FeatureGroup = 'now' | 'with_macro' | 'not_here'

export interface SetupFeature { id: string; group: FeatureGroup; label: string; note?: string | null }
/** `elyir-bench --json check`'s expectations(), as the installer saved it. */
export interface SetupBoard { board?: string; verdict?: string; why_not?: string | null; differences?: string[]; note?: string | null }
export interface SetupRow { id: SetupRowId; state?: ScreenState; why?: string | null; now?: number; with_macro?: number }
export interface SetupInfo {
  name: string
  name_from: 'mainsail' | 'hostname' | 'you'
  /** The printer's public name on the relay: off, claimed and waiting for Elyir to approve it, or on */
  secure_link?: 'off' | 'waiting' | 'on'
  rows: SetupRow[]
  dismissed: string[]
  works: {
    board?: SetupBoard | null
    features: SetupFeature[]
    include: IncludeState
    include_why?: string | null
    include_text: string
    slicer_lines: { before: string; after: string }
  }
}

export type RowIcon = 'bell' | 'screen' | 'list' | 'check'
export type RowPress = 'push_on' | 'pair_here' | 'screen_try' | 'screen_ok'

/** One row of the card, as drawn: c-ready, c-ready-later, c-screen-prep, c-screen-cant. */
export interface RowView {
  id: SetupRowId
  icon: RowIcon
  title: string
  line: string
  done: boolean
  amber?: boolean                 // the screen can't: said on the card, nothing changed
  progress?: boolean              // fetching the screen's parts: a bar with no percentage (apt gives none)
  button?: { label: string; press: RowPress; primary: boolean }
  opens?: 'works'                 // a chevron: the row opens What works
}

export const possessive = (name: string) => `${name}'s`

// Why this phone can't turn notifications on here: the same words as Care's Notifications row
const PUSH_WHY: Partial<Record<PushStatus, string>> = {
  'needs-install': 'To get them on this iPhone, tap Share, then Add to Home Screen, and open the printer from there.',
  insecure: "They need the printer's secure link, which isn't set up yet.",
  'no-door': "This printer can't send notifications yet.",
  blocked: 'Notifications are turned off for this page in your browser settings.',
  unsupported: "This browser can't show notifications from the printer.",
}

/** This page can't have notifications (plain http at home); the secure link says what comes next. */
export function insecureNotifyRow(link: SetupInfo['secure_link'], name: string): RowView {
  const row = { id: 'notify' as const, icon: 'bell' as const, title: 'Hear when a print needs you', done: false }
  if (link === 'waiting') {
    return { ...row, line: `They come once Elyir approves ${possessive(name)} secure link, usually within a day.` }
  }
  if (link === 'on') {
    return { ...row, line: `They work from ${possessive(name)} secure link: this phone goes there, paired.`,
             button: { label: 'Set up', press: 'pair_here', primary: true } }
  }
  return { ...row, line: PUSH_WHY.insecure ?? '' }
}

export function notifyRow(push: PushStatus): RowView {
  if (push === 'on') return { id: 'notify', icon: 'check', title: 'Notifications on', line: 'This phone', done: true }
  if (push === 'off') {
    return { id: 'notify', icon: 'bell', title: 'Hear when a print needs you', line: 'On this phone', done: false,
             button: { label: 'Turn on', press: 'push_on', primary: true } }
  }
  return { id: 'notify', icon: 'bell', title: 'Hear when a print needs you', line: PUSH_WHY[push] ?? '', done: false }
}

export function screenRow(state: ScreenState, name: string, why?: string | null): RowView {
  const s = `${possessive(name)} screen`
  switch (state) {
    case 'fetching':
      return { id: 'screen', icon: 'screen', title: `Getting ${s} ready`,
               line: 'Fetching what it needs. KlipperScreen stays on until then.', done: false, progress: true }
    case 'trial':
      return { id: 'screen', icon: 'screen', title: `Trying it on ${s}`, line: "Keep or go back on the printer's screen", done: false }
    case 'done':
      return { id: 'screen', icon: 'check', title: `${cap(s)} runs ${PRODUCT}`, line: 'Care › Printer screen to change', done: true }
    case 'kept_klipperscreen':
      return { id: 'screen', icon: 'check', title: `${cap(s)} stays on KlipperScreen`, line: '', done: true,
               button: { label: 'Try again', press: 'screen_try', primary: false } }
    case 'cant':
      return { id: 'screen', icon: 'screen', title: `${cap(s)} stays on KlipperScreen`, line: why ?? '', done: false, amber: true,
               button: { label: 'OK', press: 'screen_ok', primary: false } }
    default:
      return { id: 'screen', icon: 'screen', title: `Use it on ${s}`, line: 'KlipperScreen comes back with a tap', done: false,
               button: { label: 'Try it', press: 'screen_try', primary: false } }
  }
}
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

/** The works row's second line: "Most of it, and 3 more with one line" (c-ready). */
export function worksLine(withMacro: number, include: IncludeState): string {
  switch (include) {
    case 'on': return `With ${possessive(PRODUCT)} start macro`
    case 'adding': return `Adding ${possessive(PRODUCT)} start macro…`
    case 'removing': return `Taking ${possessive(PRODUCT)} start macro out…`
    case 'failed': return "The start macro didn't go in"
    default: return withMacro > 0 ? `Most of it, and ${withMacro} more with one line` : 'Everything it can do here'
  }
}

export function worksRow(row: SetupRow, name: string, include: IncludeState): RowView {
  const done = include === 'on'
  return { id: 'works', icon: done ? 'check' : 'list', title: `What works on ${name}`,
           line: worksLine(row.with_macro ?? 0, include), done, opens: 'works' }
}

/** The card's rows, in the boards' order, without the ones closed with ×. The notifications row waits
 *  until this phone has said whether it has push (null: still asking), so it never flickers. */
export function cardRows(info: SetupInfo | null, push: PushStatus | null): RowView[] {
  if (!info) return []
  const out: RowView[] = []
  const order: SetupRowId[] = ['notify', 'screen', 'works']
  for (const id of order) {
    const row = info.rows.find((r) => r.id === id)
    if (!row || info.dismissed.includes(id)) continue
    if (id === 'notify') {
      if (push === 'insecure') out.push(insecureNotifyRow(info.secure_link, info.name))
      else if (push) out.push(notifyRow(push))
    } else if (id === 'screen') {
      out.push(screenRow(row.state ?? 'offer', info.name, row.why))
    } else {
      out.push(worksRow(row, info.name, info.works.include))
    }
  }
  return out
}

export const leftCount = (rows: RowView[]) => rows.filter((r) => !r.done).length
export const leftWords = (n: number) => `${n} left`

/** On the phone while the printer says open and something is left; done rows tick off until then (c-ready-later). */
export const cardShown = (open: boolean, rows: RowView[]) => open && leftCount(rows) > 0

/** The card's last line, before "· Change": where the name came from. */
export function nameLine(name: string, from: SetupInfo['name_from']): string {
  if (from === 'mainsail') return `Called ${name}, from Mainsail`
  if (from === 'hostname') return `Called ${name}, from its network name`
  return `Called ${name}`
}

/** "1:48" */
export function countdown(seconds: number): string {
  const s = Math.max(0, Math.ceil(seconds))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

/** What's left of the trial, counted on from when the printer last said: seconds_left at `at` (ms). */
export const secondsLeft = (said: number, at: number, now: number) => Math.max(0, said - (now - at) / 1000)

/** The panel's trial bar (c-panel-try). */
export const TRIAL_ASK = `Keep ${PRODUCT} here?`
export const trialWords = (seconds: number) => `Going back in ${countdown(seconds)}`

// ---- What works (c-works) ----------------------------------------------------------------------

export const WORKS_SUB = 'Found by looking at the printer. Nothing here was changed.'
export const GROUP_LABELS: Record<FeatureGroup, string> = {
  now: 'Works now',
  with_macro: `With ${possessive(PRODUCT)} start macro`,
  not_here: 'Not on this printer',
}
export const ADD_MACRO = `Add ${possessive(PRODUCT)} start macro…`
export const REMOVE_MACRO = `Remove ${possessive(PRODUCT)} start macro…`

export interface FeatureGroupView { group: FeatureGroup; label: string; items: SetupFeature[] }

/** Works now, then what the start macro brings, then what this printer lacks; empty groups left out. */
export function featureGroups(features: SetupFeature[]): FeatureGroupView[] {
  return (['now', 'with_macro', 'not_here'] as FeatureGroup[])
    .map((group) => ({ group, label: GROUP_LABELS[group], items: features.filter((f) => f.group === group) }))
    .filter((g) => g.items.length > 0)
}

// ---- The one line (c-include), and taking it out again -------------------------------------

export const INCLUDE_YOURS = '… your start G-code, as it is …'

/** What the copy button puts on the clipboard: both lines, with a comment where theirs goes. */
export const slicerCopy = (lines: { before: string; after: string }) => `${lines.before}\n; ${INCLUDE_YOURS}\n${lines.after}`

/** The slicer line split for drawing: the macro's name bold, its settings plain. */
export function macroParts(line: string): [string, string] {
  const i = line.indexOf(' ')
  return i < 0 ? [line, ''] : [line.slice(0, i), line.slice(i)]
}

export interface IncludeWords { title: string; button: string; busy: string | null; removing: boolean }

/** The include sheet's title and button for each state of the include. */
export function includeWords(include: IncludeState): IncludeWords {
  if (include === 'on' || include === 'removing') {
    return { title: 'Take the line out of printer.cfg', button: 'Remove and restart Klipper', removing: true,
             busy: include === 'removing' ? 'Taking it out, then Klipper restarts…' : null }
  }
  return { title: 'Add one line to printer.cfg', button: 'Add and restart Klipper', removing: false,
           busy: include === 'adding' ? 'Adding it, then Klipper restarts…' : null }
}

/** A state the printer moves on from by itself: the card asks again every few seconds. */
export function settling(info: SetupInfo | null): boolean {
  if (!info) return false
  const screen = info.rows.find((r) => r.id === 'screen')?.state
  return screen === 'fetching' || screen === 'trial' || info.works.include === 'adding' || info.works.include === 'removing'
}
