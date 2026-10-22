// Setting a Happy Hare or AFC unit up from the screen (design/unit-setup/, B, stage 2, picked 22 October 2026): which
// unit by its picture, which board it's wired to (and how many slots), then Bench installs it and stage 1's Check and
// measure carries on as steps 4 and 5. The printer runs it and words it (printer/unit_setup.py); this is what the
// flow draws from that, and where it's offered.
//
// Pure, so tests/unit-setup.test.ts can pin it; the flow, Materials and Care use it.
import type { IntentAction } from './types'

export type UnitSetupStep = 'unit' | 'board' | 'installing' | 'failed' | 'installed' | 'putting_back' | 'put_back'

export interface UnitSetupUnit { id: string; name: string; kind: 'happy_hare' | 'afc'; line: string }
export interface UnitSetupBoard {
  family: string
  name: string
  /** "v1.0, v1.1 or v2", or "4 slots" for a board with one version */
  line: string
  versions: { board: string; label: string }[]
  /** The board on USB that Klipper doesn't use yet looks like this one. */
  probably: boolean
  board: string
}
export interface UnitSetupProgressStep { id: string; label: string; sub: string | null; state: 'done' | 'now' | 'next' | 'failed' }

/** The intent's unit_setup (UnitSetup.view): null when no setup is going, or once the check has taken over. */
export interface UnitSetupView {
  step: UnitSetupStep
  n: number
  of: number
  /** "Set up a filament unit · ERCF v2 on a BTT MMB" */
  where: string
  looking: boolean
  unit: string | null
  board: string | null
  family: string | null
  units: UnitSetupUnit[]
  boards: UnitSetupBoard[]
  slots: { choices: number[]; value: number | null } | null
  found: string | null
  /** Several boards Klipper doesn't use yet: which one is the unit's. */
  ports: { mcu: string; label: string }[]
  mcu: string | null
  guides: { name: string; url: string }[]
  /** "Happy Hare 4.1" */
  program: string | null
  headline: string | null
  headline_phone: string | null
  detail: string | null
  why: string | null
  progress: { steps: UnitSetupProgressStep[]; pct: number; words: string; of: number } | null
  note: { title: string; text: string; foot: string } | null
  next: { title: string; text: string } | null
  actions: IntentAction[]
}

/** Set one up, or Put it back: the action and why it can't run right now (null when it can). */
export interface UnitSetupOffer { action: IntentAction; why: string | null; line?: string }

export const SETUP_TITLE = 'Set up a filament unit'

/** The flow takes the screen while a setup is going, at home, unless this phone handed it to the printer's screen. */
export function setupShown(us: UnitSetupView | null | undefined, away: boolean, left: boolean): boolean {
  return !!us && !away && !left
}

/** "1 of 5" … "Done", beside the dots. */
export function stepLabel(us: Pick<UnitSetupView, 'n' | 'of' | 'step'>): string {
  return us.step === 'put_back' ? 'Done' : `${us.n} of ${us.of}`
}

export function dots(us: Pick<UnitSetupView, 'n' | 'of'>): ('d' | 'n' | '')[] {
  return Array.from({ length: us.of }, (_, i) => (i < us.n - 1 ? 'd' : i === us.n - 1 ? 'n' : ''))
}

/** The back button: Close on the first step, Back on the board, nothing while the installer runs. */
export function backAction(us: UnitSetupView): IntentAction | null {
  const id = us.step === 'board' ? 'unit_setup_back' : 'unit_setup_close'
  return us.actions.find((a) => a.id === id) ?? null
}

/** The buttons at the bottom right, quiet ones first and the main one last. On the first step Close is the back
 *  button only (board b-unit); Back is both (b-board). */
export function barButtons(us: UnitSetupView): IntentAction[] {
  const list = us.step === 'unit' ? us.actions.filter((a) => a.id !== 'unit_setup_close') : us.actions
  return [...list.filter((a) => !a.primary), ...list.filter((a) => a.primary)]
}

/** The main button is drawn but can't be tapped yet: no unit picked, or no board or port to set it up on. */
export function primaryReady(us: UnitSetupView): boolean {
  if (us.step === 'unit') return !!us.unit && !us.looking
  if (us.step === 'board') return !!us.board && !!us.mcu && !us.looking
  return true
}

/** The chosen board family's versions, when it has more than one (a small row under the tiles). */
export function versionsOf(us: UnitSetupView): { board: string; label: string }[] {
  const fam = us.boards.find((b) => b.family === us.family)
  return fam && fam.versions.length > 1 ? fam.versions : []
}

/** The action a tap sends: a unit, a board (its first version), a version, a slot count or a port. */
export function pick(kind: 'unit' | 'board' | 'slots' | 'port', value: string | number): IntentAction {
  const key = kind === 'port' ? 'mcu' : kind
  return { id: `unit_setup_${kind}`, label: String(value), primary: false, style: 'default', args: { [key]: value } }
}

/** "Something else" and "Another board": the two projects' own guides (as in direction C). */
export function guidesCard(us: UnitSetupView, what: 'unit' | 'board'): { title: string; text: string; guides: UnitSetupView['guides'] } {
  const unit = us.units.find((u) => u.id === us.unit)
  const which = what === 'board' && unit ? us.guides.filter((g) => us.program?.startsWith(g.name)) : us.guides
  return {
    title: what === 'unit' ? 'Their guides, on your phone' : 'Not on the list yet',
    text: what === 'unit'
      ? 'Bench sets up the units on this page itself. For another one, its own software has a guide; once it runs, Bench finds the unit and checks it.'
      : `Bench sets up ${unit?.name ?? 'this unit'} on the boards shown. For another board, ${which.map((g) => g.name).join(' and ')}'s guide shows how; once it runs, Bench finds the unit and checks it.`,
    guides: which.length ? which : us.guides,
  }
}

/** Care's Filament unit rows when there's no unit (Set one up) or a copy is kept (Put it back). */
export function careSetupRows(offer: UnitSetupOffer | null | undefined, putback: UnitSetupOffer | null | undefined):
  { key: string; name: string; line: string; action: IntentAction; why: string | null }[] {
  const rows = []
  if (offer) {
    rows.push({ key: 'setup', name: 'Filament unit', line: offer.why ?? 'None found. Bench sets up a Box Turtle, Night Owl, ERCF or Tradrack.', action: offer.action, why: offer.why })
  }
  if (putback) {
    rows.push({ key: 'putback', name: 'Filament unit · Your old settings', line: putback.line ?? putback.why ?? '', action: putback.action, why: putback.why })
  }
  return rows
}
