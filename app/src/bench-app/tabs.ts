// The Bench Box's other tabs (design/bench-box/, D: Printers, Print, Spools, Care; Print's shelf is shelf.ts). Each gathers what every
// printer already says about itself into one place; tapping a printer opens its own screen, where the doing
// is. Pure, so tests/bench-tabs.test.ts can pin it; the pages draw what it says.

import type { IntentSpool } from '../intent/types'
import type { CareItem } from '../intent/care'
import type { BenchPrinter } from './bench'

const NUMBERS = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten']
const count = (n: number) => NUMBERS[n] ?? String(n)
const and = (xs: string[]) => (xs.length < 2 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`)
const live = (ps: BenchPrinter[]) => ps.filter((p) => p.live && p.intent)
const byName = (a: { name: string }, b: { name: string }) => a.name.localeCompare(b.name)

// ── Print: whichever is free (D-print) ─────────────────────────────────────────────────────────────────

export interface FreeRow {
  id: string
  name: string
  line: string       // why it's where it is: "Free now · White PLA loaded." (its first sentence), "After the phone stand, about 4:20 pm"
  free: boolean      // can take a print now
  stopped: boolean   // needs a person before anything else
}

/** Every printer that's on, the soonest free first: free now, free once the bed is cleared, then printing by
 *  when it's done, then the ones that stopped. */
export function whicheverIsFree(ps: BenchPrinter[]): FreeRow[] {
  const rank = (p: BenchPrinter): [number, number] => {
    const i = p.intent!
    if (i.state === 'ready') return [0, 0]
    if (i.state === 'finished') return [1, 0]
    if (i.state === 'printing' || i.state === 'preparing') return [2, i.job?.remaining_s ?? 9e9]
    return [3, 0]
  }
  return live(ps)
    .map((p) => ({ p, r: rank(p) }))
    .sort((a, b) => a.r[0] - b.r[0] || a.r[1] - b.r[1] || byName(a.p, b.p))
    .map(({ p, r }) => {
      const i = p.intent!
      const job = i.job?.name ? i.job.name.charAt(0).toLowerCase() + i.job.name.slice(1) : 'this print'
      const line = r[0] === 0 ? ['Free now', i.detail.split(/(?<=\.)\s/)[0]].filter(Boolean).join(' · ')
        : r[0] === 1 ? 'Free once the bed is cleared'
        : r[0] === 2 ? (i.job?.eta_clock ? `After the ${job}, about ${i.job.eta_clock}` : `After the ${job}`)
        : `Stopped: ${i.headline}`
      return { id: p.id, name: p.name, line, free: r[0] === 0, stopped: r[0] === 3 }
    })
}

// ── Spools ────────────────────────────────────────────────────────────────────────────────────────────

export interface SpoolCell {
  slot: number
  color: string | null
  name: string        // "White PLA", "Empty"
  meta: string        // "in use", "120 g, low", "800 g"
  tone: 'amber' | 'accent' | null
}
export interface SpoolCard {
  id: string
  name: string
  spools: SpoolCell[]
  short: number       // empty or low: the card leads, and is outlined
}

const words = (s: IntentSpool) => s.name || [s.material?.toUpperCase()].filter(Boolean).join(' ') || 'Unknown spool'
// an empty slot in a unit is just room; empty is only short when it's the printer's one spool, or feeding
function cellOf(s: IntentSpool, only: boolean): SpoolCell {
  if (s.status === 'empty') return only || s.in_use
    ? { slot: s.slot, color: null, name: 'Empty', meta: 'put one in', tone: 'amber' }
    : { slot: s.slot, color: null, name: 'Empty', meta: '', tone: null }
  const meta = s.in_use ? 'in use' : s.status === 'low' ? (s.grams ? `${s.grams} g, low` : 'running low') : s.grams ? `${s.grams} g` : ''
  return { slot: s.slot, color: s.color, name: words(s), meta, tone: s.status === 'low' ? 'amber' : s.in_use ? 'accent' : null }
}

/** Every printer's spools, the ones running short first. A printer that reports no spools isn't listed. */
export function spoolCards(ps: BenchPrinter[]): SpoolCard[] {
  return live(ps)
    .filter((p) => p.intent!.spools?.length)
    .map((p) => {
      const spools = [...p.intent!.spools].sort((a, b) => a.slot - b.slot).map((x, _, all) => cellOf(x, all.length === 1))
      return { id: p.id, name: p.name, spools, short: spools.filter((c) => c.tone === 'amber').length }
    })
    .sort((a, b) => (b.short ? 1 : 0) - (a.short ? 1 : 0) || byName(a, b))
}

/** "Studio's slot 2 is running low." / "Two spools need you: …" / "Every spool is loaded." */
export function spoolSentence(cards: SpoolCard[]): string {
  if (!cards.length) return 'No printer has said what it has loaded.'
  const short = cards.flatMap((c) => c.spools.filter((s) => s.tone === 'amber').map((s) => ({ c, s })))
  const at = ({ c, s }: { c: SpoolCard; s: SpoolCell }) => (c.spools.length > 1 ? `${c.name}'s slot ${s.slot}` : c.name)
  if (short.length === 1) return `${at(short[0])} ${short[0].s.name === 'Empty' ? 'is empty' : 'is running low'}.`
  if (short.length && short.length <= 3) return `${count(short.length)} spools need you: ${and(short.map(at))}.`
  if (short.length) return `${count(short.length)} spools need you, on ${and([...new Set(short.map(({ c }) => c.name))])}.`
  const n = cards.reduce((k, c) => k + c.spools.length, 0)
  return n === 1 ? 'The spool is loaded.'
    : `Every spool is loaded: ${n} on ${cards.length === 1 ? 'one printer' : `${count(cards.length).toLowerCase()} printers`}.`
}

/** What's loaded across the bench by material, for "where's my PETG": [["PLA", ["Workshop", "Desk"]], ...]. */
export function byMaterial(ps: BenchPrinter[]): [string, string[]][] {
  const m = new Map<string, Set<string>>()
  for (const p of live(ps)) for (const s of p.intent!.spools ?? []) {
    if (s.status === 'empty' || !s.material) continue
    const k = s.material.toUpperCase()
    m.set(k, (m.get(k) ?? new Set()).add(p.name))
  }
  return [...m].map(([k, v]) => [k, [...v].sort()] as [string, string[]]).sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]))
}

// ── Care ──────────────────────────────────────────────────────────────────────────────────────────────

export interface CareRow extends CareItem {
  printer: string
  printerId: string
}

/** Every printer's care, due first, then the nearest. Snoozed items wait with the rest. */
export function careRows(ps: BenchPrinter[]): CareRow[] {
  return live(ps)
    .flatMap((p) => (p.intent!.care?.items ?? []).map((c) => ({ ...c, printer: p.name, printerId: p.id })))
    .sort((a, b) => Number(b.due && !b.snoozed) - Number(a.due && !a.snoozed) || b.progress - a.progress || a.printer.localeCompare(b.printer))
}

/** "Time to clean the nozzle on Workshop." / "Three things are due, on Workshop and Studio." / "Nothing is due. Next: …"
 *  Care items are named as things to do ("Clean the nozzle"), the printer's own words. */
export function careSentence(rows: CareRow[]): string {
  if (!rows.length) return 'No printer counts its care yet.'
  const due = rows.filter((r) => r.due && !r.snoozed)
  const todo = (r: CareRow) => `${r.name.charAt(0).toLowerCase() + r.name.slice(1)} on ${r.printer}`
  if (due.length === 1) return `Time to ${todo(due[0])}.`
  if (due.length) return `${count(due.length)} things are due, on ${and([...new Set(due.map((r) => r.printer))])}.`
  const next = rows.find((r) => !r.due)
  return next ? `Nothing is due. Next: ${todo(next)}, ${next.label}.` : 'Nothing is due.'
}
