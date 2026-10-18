// Printing a model from the Bench Box's shelf (design/bench-print/, A, picked 4 October 2026): the filaments loaded
// across the bench, and for a model in one of them, where it can print, the soonest free first, with why for every
// other printer. Pure, so tests/bench-shelf.test.ts can pin it; ShelfPage and ModelPage draw what it says.

import type { IntentSpool } from '../intent/types'
import type { BenchPrinter } from './bench'
import { whicheverIsFree, type FreeRow } from './tabs.ts'
import { COLORS } from '../components/materials/palette.ts'

const SAME = 70   // the intent layer's "same colour" distance (palette.ts, elyir_bench_intent.py)

const rgb = (hex: string) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))
function near(a: string | null, b: string | null): boolean {
  if (!a || !b || !/^#[0-9a-f]{6}$/i.test(a) || !/^#[0-9a-f]{6}$/i.test(b)) return a === b
  const [x, y] = [rgb(a), rgb(b)]
  return Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2]) < SAME
}
/** "White", from the palette people pick from; '' when it's no colour on the list. */
export function colorName(hex: string | null): string {
  if (!hex) return ''
  let best = '', d = SAME
  for (const c of COLORS) {
    const [x, y] = [rgb(hex), rgb(c.hex)]
    const e = Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2])
    if (e < d) { best = c.name; d = e }
  }
  return best
}

export interface Filament {
  key: string
  material: string        // PLA
  color: string | null    // #F4F4F2
  name: string            // White PLA, or one of yours: Polymaker PolyTerra PLA
  on: string[]            // the printers it's loaded on
  preset?: string         // one of yours: the Orca filament preset it slices with
  mine?: string           // one of yours: its id
  sub?: string            // its second line: "Charcoal · Workshop slot 3", "Gray · not loaded"
}

/** One of your filaments (bench/filaments.py; design/bench-material/, B). */
export interface MyFilament { id: string; preset: string; name: string; brand: string; material: string; color: string }

const loaded = (s: IntentSpool) => (s.status === 'ready' || s.status === 'low') && !!s.material
/** One spool nobody has described (a Kobra just added): its own check asks what's on it at the start, as its own Print does. */
export const asksWhatsLoaded = (p: BenchPrinter) => {
  const sp = p.intent?.spools ?? []
  return sp.length === 1 && !!sp[0].direct && !loaded(sp[0])
}
export const ASKS = "it asks what's loaded when it starts"
const words = (material: string, color: string | null) => [colorName(color), material].filter(Boolean).join(' ')

/** Every filament loaded on a printer that's on, the most widely loaded first: what a model can be printed in. */
export function filaments(ps: BenchPrinter[]): Filament[] {
  const out: Filament[] = []
  for (const p of ps.filter((x) => x.live && x.intent)) {
    for (const s of p.intent!.spools ?? []) {
      if (!loaded(s)) continue
      const material = s.material!.toUpperCase()
      const f = out.find((x) => x.material === material && near(x.color, s.color))
      if (f) { if (!f.on.includes(p.name)) f.on.push(p.name) }
      else out.push({ key: `${material}${s.color ?? ''}`, material, color: s.color, name: words(material, s.color), on: [p.name] })
    }
  }
  return out.sort((a, b) => b.on.length - a.on.length || a.name.localeCompare(b.name))
}

/** "Polymaker PolyTerra PLA": the brand in front, unless the name already starts with it ("Generic PLA"). */
export function filamentTitle(f: { name: string; brand: string }): string {
  return !f.brand || f.name.toLowerCase().startsWith(f.brand.toLowerCase()) ? f.name : `${f.brand} ${f.name}`
}

/** Your filaments as In lists them: each with where it's loaded (a spool of its material and color), loaded ones first. */
export function yourFilaments(ps: BenchPrinter[], mine: MyFilament[]): Filament[] {
  const rows = mine.map((m): Filament => {
    const places: string[] = [], on: string[] = []
    for (const p of ps.filter((x) => x.live && x.intent)) {
      const sp = (p.intent!.spools ?? []).filter((s) => loaded(s) && s.material!.toUpperCase() === m.material && near(s.color, m.color))
      if (!sp.length) continue
      on.push(p.name)
      places.push(sp[0].direct ? p.name : `${p.name} slot ${sp.map((s) => s.slot + 1).join(', ')}`)
    }
    return { key: `mine:${m.id}`, material: m.material, color: m.color, name: filamentTitle(m), on, preset: m.preset, mine: m.id,
             sub: [colorName(m.color) || 'Its color', places.length ? places.join(', ') : 'not loaded'].join(' · ') }
  })
  return [...rows.filter((r) => r.on.length), ...rows.filter((r) => !r.on.length)]
}

/** The loaded filament a model was last printed in, when it's still loaded somewhere. */
export function filamentFor(fils: Filament[], material: string | null | undefined, color: string | null | undefined): Filament | null {
  if (!material) return null
  return fils.find((f) => f.material === material.toUpperCase() && near(f.color, color ?? null)) ?? null
}

/** What the box knows about setting a model up for each printer (GET /bench/printable). */
export type Printable = Record<string, { materials?: string[]; slots?: number | null; error?: string }>

const MATERIAL_ORDER = ['PLA', 'PETG', 'ABS', 'ASA', 'TPU']
/** What a model can be printed in: every filament loaded across the bench, and, when a printer asks what's on its one
 *  spool, each material it has settings for, in any color ("PLA"). */
export function choices(ps: BenchPrinter[], printable: Printable, mine: MyFilament[] = []): Filament[] {
  if (mine.length) {
    // yours, then what's loaded that isn't one of yours, as today; a printer that asks what's loaded asks for one of yours
    const yours = yourFilaments(ps, mine)
    const rest = filaments(ps).filter((f) => !yours.some((y) => y.material === f.material && near(y.color, f.color)))
    return [...yours, ...rest.map((f) => ({ ...f, sub: `${f.on.join(', ')} · not one of yours yet` }))]
  }
  const out = filaments(ps)
  const asking = ps.filter((p) => p.live && p.intent && asksWhatsLoaded(p))
  const mats = [...new Set(asking.flatMap((p) => printable[p.id]?.materials ?? []))]
    .sort((a, b) => (MATERIAL_ORDER.indexOf(a) + 1 || 99) - (MATERIAL_ORDER.indexOf(b) + 1 || 99) || a.localeCompare(b))
  return [...out, ...mats.map((m) => ({ key: m, material: m, color: null, name: `Any ${m}`, on: asking.map((p) => p.name) }))]
}

export interface PrintOnRow extends FreeRow {
  fits: boolean           // can take this model in this filament (now or when it's free)
  slot: number | null     // the slicer's slot (1-based), or null for a printer with one spool
  now: boolean            // free, or free once its bed is cleared: it can start once someone says the bed is clear.
                          // A printer that's printing only gets the file, to start there once it's done.
  asks?: boolean          // its one spool isn't described: it can take any filament it has settings for, and asks at the start
}

/** The printers worth a time on the model page (design/bench-look/, C): each one the box can set this filament up for,
 *  with it loaded or not (one with another filament loaded shows its time grayed); not one that's stopped. */
export function timeable(rows: PrintOnRow[], printable: Printable, want: Filament | null): string[] {
  if (!want) return []
  return rows.filter((r) => !r.stopped && !printable[r.id]?.error && !!printable[r.id]?.materials?.includes(want.material)).map((r) => r.id)
}

/** Where a model in this filament can print: the soonest free with it loaded first, then the rest, each saying why. */
export function printOn(ps: BenchPrinter[], want: Filament | null, printable: Printable): PrintOnRow[] {
  const rows = whicheverIsFree(ps).map((row): PrintOnRow => {
    const r = { ...row, now: row.free || row.line.startsWith('Free once') }
    const p = ps.find((x) => x.id === r.id)!
    const can = printable[r.id]
    if (r.stopped) return { ...r, fits: false, slot: null }         // what stopped it comes first
    if (can?.error) return { ...r, fits: false, slot: null, line: "The box can't set a model up for it yet" }
    if (!want) return { ...r, fits: true, slot: null }
    const spools = (p.intent!.spools ?? []).filter(loaded)
    const s = spools.find((x) => x.material!.toUpperCase() === want.material && (want.color === null || near(x.color, want.color)))
    if (can?.materials && !can.materials.includes(want.material)) {
      return { ...r, fits: false, slot: null, line: `It has no ${want.material} settings` }
    }
    if (!s && asksWhatsLoaded(p)) {
      return { ...r, fits: true, slot: null, asks: true, line: r.free ? `Free now: ${ASKS}` : `${r.line} · ${ASKS}` }
    }
    if (!s) {
      const has = [...new Set(spools.map((x) => words(x.material!.toUpperCase(), x.color)))].slice(0, 2)
      return { ...r, fits: false, slot: null, line: has.length ? `It has ${has.join(' and ')}, not ${want.name}` : 'Nothing is loaded' }
    }
    const slot = s.direct ? null : s.slot + 1
    const where = slot && spools.length > 1 ? `${want.name} in slot ${slot}` : `it has ${want.name}`
    return { ...r, line: r.free ? `Free now: ${where}` : `${r.line} · ${where}`, fits: true, slot }
  })
  return [...rows.filter((r) => r.fits && !r.asks), ...rows.filter((r) => r.fits && r.asks), ...rows.filter((r) => !r.fits)]
}

/** The printer picked to begin with: the soonest free that fits; a printer asked for (a tile's Print a model) wins. */
export function firstPick(rows: PrintOnRow[], asked?: string | null): PrintOnRow | null {
  return rows.find((r) => r.fits && r.id === asked) ?? rows.find((r) => r.fits) ?? null
}

/** The line over the shelf: which printer is free, or which is next. */
export function shelfSentence(ps: BenchPrinter[]): string {
  const rows = whicheverIsFree(ps)
  const free = rows.filter((r) => r.free)
  if (free.length === 1) return `${free[0].name} is free. What should it print?`
  if (free.length) return `${free.length === 2 ? 'Two' : free.length} printers are free. What should they print?`
  const next = rows.find((r) => !r.stopped)
  if (!next) return rows.length ? 'No printer is free right now.' : 'No printer is on.'
  const about = next.line.match(/about (.+)$/)?.[1]
  return next.line.startsWith('Free once') ? `${next.name} is free once its bed is cleared.`
    : `Nothing is free right now. ${next.name} is next${about ? `, about ${about}` : ''}.`
}

/** A shelf model's second line: where and when it was last printed, or when it was added. */
export function lastLine(it: { added: number; last: { printer_name: string; copies: number; material: string | null; color: string | null; at: number } | null }, now: Date): string {
  const when = (t: number) => {
    const d = new Date(t * 1000), days = Math.round((startOf(now) - startOf(d)) / 864e5)
    return days === 0 ? 'today' : days === 1 ? 'yesterday' : days < 7 ? d.toLocaleDateString('en-US', { weekday: 'long' }) : d.toLocaleDateString('en-US', { day: 'numeric', month: 'short' })
  }
  if (!it.last) return `Added ${when(it.added)}`
  const l = it.last
  const what = l.material ? words(l.material.toUpperCase(), l.color) : ''
  return [l.printer_name, when(l.at), [what, l.copies > 1 ? `× ${l.copies}` : ''].filter(Boolean).join(' ')].filter(Boolean).join(' · ')
}
/** A shelf card: a model printed from a printer's own Print says so in its tag (design/bench-shelf/, A), and its line
 *  doesn't name that printer again while that print is still its last. */
export function shelfCard(it: Parameters<typeof lastLine>[0] & { from?: { printer_name: string; at: number } | null }, now: Date):
  { tag: string | null; line: string } {
  if (!it.from) return { tag: null, line: lastLine(it, now) }
  const tag = `From ${it.from.printer_name}'s Print`
  const line = lastLine(it, now)
  return { tag, line: it.last && it.last.at === it.from.at ? line.replace(`${it.from.printer_name} · `, '') : line }
}
const startOf = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()

// ── Tidy A (design/bench-queue/): the last 30 days on show, older ones folded into one row, never deleted ──

const RECENT_DAYS = 30
type Dated = { added: number; last: { at: number } | null }
export function foldShelf<T extends Dated>(items: T[], now: Date): { recent: T[]; older: T[]; since: string | null } {
  const cut = now.getTime() / 1000 - RECENT_DAYS * 86400
  const when = (it: T) => Math.max(it.added, it.last?.at ?? 0)
  const recent = items.filter((it) => when(it) >= cut)
  const older = items.filter((it) => when(it) < cut)
  const newest = older.length ? new Date(Math.max(...older.map(when)) * 1000) : null
  return { recent, older, since: newest ? newest.toLocaleDateString('en-US', { month: 'long' }) : null }
}

// ── Queue A (design/bench-queue/): what's waiting, as the box's service says (bench/bench_queue.py) ──

export interface QueueItem {
  id: string
  shelf: string
  name: string            // a bed's (several models, design/bench-several/) is ready to show: "Phone stand × 2, Cable clips × 4"
  copies: number          // a bed's: all its copies
  material: string
  color: string | null
  state: 'waiting' | 'setting' | 'ready'
  printer: string | null
  printer_name: string | null
  time: number | null
  line: string
  error: string | null
  models?: { shelf: string; name: string; copies: number }[]
  bed?: boolean
  on?: string | null      // the printer the plan gave a bed; it waits for that one
  on_name?: string | null
  grams?: number | null
  by?: string | null
  away?: boolean
}

/** A queued print's name: a bed's as the box says it, a model's with its copies. */
export const queueTitle = (q: { name: string; copies: number; bed?: boolean }) => (q.bed ? q.name : `${q.name}${q.copies > 1 ? ` × ${q.copies}` : ''}`)

const WAITING = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten']
/** The line over the queue: how many wait, and which printers someone can start now. */
export function queueSentence(q: QueueItem[]): string | null {
  if (!q.length) return null
  const n = WAITING[q.length] ?? String(q.length)
  const ready = [...new Set(q.filter((it) => it.state === 'ready').map((it) => it.printer_name ?? ''))]
  if (ready.length > 1) return `${n} waiting. ${ready.slice(0, -1).join(', ')} and ${ready[ready.length - 1]} can start now.`
  return `${n} waiting.${ready.length ? ` ${ready[0]} can start ${q.length === 1 ? 'it' : 'the next'} now.` : ''}`
}
