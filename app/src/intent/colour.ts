// Colour changes on a printer with a filament unit (design/colour-change/, C as the main path, A as the
// fallback). Every word here comes from the intent layer; this file only decides which of its words show,
// and what a tap sends. Pinned by tests/colour.test.ts.

import type { ColourSheet, ColourTile, Intent, IntentAction, IntentColour, PrintCheck } from './types'

/** A check that needs a sheet before anything starts: something's missing, or the file changes colour. */
export function needsSheet(check: PrintCheck): boolean {
  return !check.ok || !!check.colour
}

// ---- the Print sheet: CReady (the file names the colour), CAsk (it doesn't) -------------------------------

/** Per change: a loaded spool, "pause" (stop there and let me choose), or null (not answered yet). */
export type PlanPick = number | 'pause' | null

/** What the sheet starts with: the spool matching the file's colour, a pause where it isn't loaded, else a question. */
export function initialPicks(sheet: ColourSheet): PlanPick[] {
  return sheet.changes.map((c) => c.slot ?? (c.not_loaded ? 'pause' : null))
}

/** The spool feeding the head just before change k: what it starts with, then each spool picked before. */
export function spoolBefore(sheet: ColourSheet, picks: PlanPick[], k: number): number | null {
  for (let j = k - 1; j >= 0; j--) {
    const p = picks[j]
    if (typeof p === 'number') return p
  }
  return sheet.start.slot
}

/** The spools change k can switch to: every loaded one but the one already feeding the head. */
export function choicesFor(sheet: ColourSheet, picks: PlanPick[], k: number) {
  const before = spoolBefore(sheet, picks, k)
  return sheet.choices.filter((c) => c.slot !== before)
}

/** Print waits until every change has a spool or a pause (CAsk). */
export function canPrint(picks: PlanPick[]): boolean {
  return picks.length > 0 && picks.every((p) => p !== null)
}

/** The line under a picked spool: "Slot 2 · the file's white" for the file's own colour, else "Slot 4";
 *  for a pause, why it pauses. */
export function pickLine(sheet: ColourSheet, k: number, pick: PlanPick): string {
  const c = sheet.changes[k]
  if (pick === 'pause') return c.not_loaded && c.missing_line ? c.missing_line : c.pause_line
  if (pick === null) return ''
  if (pick === c.slot && c.named_line) return c.named_line
  return sheet.choices.find((x) => x.slot === pick)?.line ?? ''
}

/** What print_planned sends: one entry per change, `sure` for a spool of another material someone said yes to. */
export function planChanges(picks: PlanPick[], sure: number[]): { slot: number | 'pause'; sure?: true }[] {
  return picks.map((p) => {
    if (p === null) throw new Error('every change needs a spool first')
    if (p === 'pause') return { slot: 'pause' as const }
    return sure.includes(p) ? { slot: p, sure: true as const } : { slot: p }
  })
}

// ---- the pause: APause, APicked, AMissing, APhone ----------------------------------------------------

export function tileOf(colour: IntentColour | null | undefined, slot: number | null | undefined): ColourTile | null {
  if (!colour || slot == null) return null
  return colour.slots.find((t) => t.slot === slot) ?? null
}

/** Whether a tile can be picked here: it does something, and away only what needs no hands. */
export function offered(t: ColourTile | null, away: boolean): boolean {
  return !!t?.action && !(away && t.at_printer)
}

/** The steps a tap goes through before it's sent: another material is asked about once; away, a switch is
 *  confirmed once more. */
export function stagesOf(t: ColourTile, away: boolean): ('ask' | 'confirm')[] {
  const out: ('ask' | 'confirm')[] = []
  if (t.ask) out.push('ask')
  if (away && t.how === 'switch' && t.confirm_away) out.push('confirm')
  return out
}

/** The amber button and the line under the tiles, `done` steps into a tile's stages. `send` is what the button
 *  sends now; null means the button only moves to the next stage. */
export function pauseStep(t: ColourTile | null, away: boolean, done: number):
  { label: string; says: [string, string] | null; tone: 'amber' | null; send: IntentAction | null } {
  if (!t || !t.action || !offered(t, away)) return { label: '', says: null, tone: null, send: null }
  const stages = stagesOf(t, away)
  const at = Math.min(done, stages.length)
  const stage = at > 0 ? stages[at - 1] : null
  const label = stage === 'ask' ? t.ask!.label : stage === 'confirm' ? t.confirm_away!.label : t.action.label
  const says: [string, string] | null = stage === 'ask' ? [t.ask!.text, '']
    : stage === 'confirm' ? [t.confirm_away!.text, '']
    : (away ? t.says_away ?? t.says : t.says)
  if (at < stages.length) return { label, says, tone: stage ? 'amber' : null, send: null }
  const args: Record<string, unknown> = { ...(t.action.args ?? {}) }
  if (stages.includes('ask')) args.sure = true
  if (stages.includes('confirm')) args.away_ok = true
  return { label, says, tone: stage ? 'amber' : null, send: { ...t.action, label, args } }
}

/** The tiles grouped by unit, in slot order. */
export function unitsOf(colour: IntentColour): { name: string; tiles: ColourTile[] }[] {
  const by = new Map(colour.slots.map((t) => [t.slot, t]))
  const units = colour.units.length ? colour.units : [{ name: '', slots: colour.slots.map((t) => t.slot) }]
  return units.map((u) => ({ name: u.name, tiles: u.slots.map((s) => by.get(s)).filter((t): t is ColourTile => !!t) }))
}

/** The status bar's word while getting ready or changing something. A planned colour switch is part of printing
 *  (CAuto: "Printing"); one a person chose is "Changing colour" (SSwitch). */
export function preparingWord(i: Partial<Pick<Intent, 'change' | 'phase' | 'unit_setup'>> | null | undefined): string {
  const c = i?.change
  if (c) {
    if (c.kind === 'colour') return c.auto ? 'Printing' : 'Changing color'
    return c.kind === 'slot' ? 'Swapping a spool' : 'Changing filament'
  }
  if (i?.phase === 'colour_resuming') return 'Printing'
  if (i?.phase?.startsWith('unit_check')) return 'Checking the unit'   // design/unit-setup/
  if (i?.phase === 'unit_setup' || i?.unit_setup?.step === 'installing') return 'Setting up'   // Klipper's restart too
  if (i?.phase === 'turning_off') return 'Turning off'   // design/power/
  if (i?.phase === 'restarting') return 'Restarting'
  if (i?.phase === 'power_back') return "Power's back"   // design/power-loss/
  return i?.phase === 'carrying_on' ? 'Carrying on' : 'Getting ready'
}
