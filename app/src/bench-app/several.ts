// Several models from the Bench Box's shelf at once (design/bench-several/, C, picked 10 October 2026): ticking models
// on the shelf, the plan the box makes for them (bench/plan.py, docs/bench.md "Several at once"), moving a model, and
// the words on every card. The rules live in plan.py only; this says what the box answered. Pure, so
// tests/bench-several.test.ts can pin it; ShelfPage, PlanPage and MoveSheet draw what it says.

import type { BenchPrinter } from './bench'
import { costWords, howLine, howTiles, mergeHow, type BrimKind, type How, type HowChange, type PurposeOption, type Tile } from './how.ts'
import type { Editable, Purpose, SupportKind } from '../slice/plan.ts'
import { filamentFor, filaments, printOn, type Filament, type Printable, type PrintOnRow } from './shelf.ts'

/** One picked model, as POST /bench/plan takes it: a printer asked for, its own bed, or left out. */
export interface PlanPick { shelf: string; copies: number; printer?: string; bed?: 'own'; out?: true; in?: PlanFil }
/** A filament picked for a model on the plan (In on the move sheet), as POST /bench/plan takes it. */
export interface PlanFil { material: string; color: string | null; filament?: string; filament_name?: string }

export interface PlanModel { shelf: string; name: string; copies: number; of: number; picture: string | null; first: boolean; chosen?: boolean }
export type WhenKind = 'now' | 'clear' | 'next' | 'after' | 'queued' | 'waits'
export interface PlanBed {
  id: string
  printer: string | null
  printer_name: string | null
  order: number
  material: string
  color: string | null
  slot: number | null
  filament: string | null
  filament_name: string | null
  words: string
  asks: boolean
  purpose: string
  supports: string | null
  settings: Record<string, string>
  /** the models' brim when they share one; mixed when they differ (a brim never splits a bed) */
  brim?: BrimKind | null | 'mixed'
  models: PlanModel[]
  fits: boolean | null
  split: boolean
  seconds: number | null
  grams: number | null
  rough: boolean
  when: { kind: WhenKind; clock?: string | null; at?: number | null }
  start_at: number | null
  done_at: number | null
  why: string
}
export interface Cant { shelf: string; name: string | null; copies: number; why: string }
export interface Plan {
  checking: boolean
  beds: PlanBed[]
  cant: Cant[]
  out: { shelf: string; name: string }[]
  said: string[]
  free_left: { id: string; name: string }[]
  printers: number
  done_at: number | null
  ahead: number
}

const NUMBERS = ['No', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten', 'Eleven', 'Twelve']
const Count = (n: number) => NUMBERS[n] ?? String(n)
const count = (n: number) => Count(n).toLowerCase()
const ORDINAL = ['', 'First', 'Second', 'Third', 'Fourth', 'Fifth', 'Sixth']
const and = (xs: string[]) => (xs.length < 2 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`)
const lower = (s: string) => s.charAt(0).toLowerCase() + s.slice(1)
export const clock = (t: number) => new Date(t * 1000).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }).toLowerCase()

// ── picking on the shelf (C-shelf, C-select) ──

export const MOST = 50       // the box plans at most this many models at once

/** Ticking a tile: in when it wasn't, out when it was; the order picked is the plan's order. */
export function toggle(ids: string[], id: string): string[] {
  return ids.includes(id) ? ids.filter((x) => x !== id) : ids.length >= MOST ? ids : [...ids, id]
}

/** The line over the shelf while picking. */
export function pickLine(n: number): string {
  return n ? `${n} picked. The box works out where each prints.` : 'Tap the models to print together.'
}

/** The bar at the foot while picking: how many, their names, and the button. */
export function footBar(names: string[]): { count: string; names: string; go: string } {
  const n = names.length
  if (!n) return { count: 'None picked', names: '', go: 'Print' }
  const what = n === 1 ? '1 model' : `${n} models`
  return { count: what, names: names.join(', '), go: `Print ${what}` }
}

/** Each picked model with the copies it last printed with. */
export function picksOf(ids: string[], items: { id: string; last: { copies: number } | null }[]): PlanPick[] {
  return ids.map((id) => ({ shelf: id, copies: Math.max(1, items.find((it) => it.id === id)?.last?.copies ?? 1) }))
}

// The picks ride in the plan page's address (?m=), so a reload keeps them and a move:
// "a1b2~2,c3d4~4~on:workshop,e5f6~1~own:,g7h8~1~out", and a filament picked: ~in:{"material":"PETG","color":"#8A8D91"}
export function picksToQuery(picks: PlanPick[]): string {
  return picks.map((p) => [p.shelf, p.copies, ...(p.out ? ['out'] : p.bed === 'own' ? [`own:${p.printer ?? ''}`] : p.printer ? [`on:${p.printer}`] : []),
    ...(p.in ? [`in:${JSON.stringify(p.in)}`] : [])]
    .map((x) => encodeURIComponent(String(x))).join('~')).join(',')
}
export function picksFromQuery(q: unknown): PlanPick[] {
  if (typeof q !== 'string' || !q) return []
  const out: PlanPick[] = []
  for (const part of q.split(',')) {
    const [shelf, n, ...rest] = part.split('~').map(decodeURIComponent)
    const how = rest.find((x) => !x.startsWith('in:'))
    const fil = rest.find((x) => x.startsWith('in:'))
    if (!shelf || out.some((p) => p.shelf === shelf)) continue
    const p: PlanPick = { shelf, copies: Math.max(1, Math.min(200, Number(n) || 1)) }
    if (how === 'out') p.out = true
    else if (how?.startsWith('own:')) { p.bed = 'own'; if (how.slice(4)) p.printer = how.slice(4) }
    else if (how?.startsWith('on:') && how.slice(3)) p.printer = how.slice(3)
    if (fil) {
      try {
        const f = JSON.parse(fil.slice(3))
        if (f && typeof f.material === 'string') p.in = f
      } catch { /* a hand-edited address: the box's own choice */ }
    }
    out.push(p)
  }
  return out.slice(0, MOST)
}

/** One pick changed: a key given as undefined is dropped (back to the box's choice). */
export function setPick(picks: PlanPick[], shelf: string, patch: Partial<PlanPick>): PlanPick[] {
  return picks.map((p) => {
    if (p.shelf !== shelf) return p
    const n = { ...p, ...patch } as Record<string, unknown>
    for (const k of Object.keys(n)) if (n[k] === undefined) delete n[k]
    n.copies = Math.max(1, Math.min(200, Number(n.copies) || 1))
    return n as unknown as PlanPick
  })
}

// ── the plan (C-plan) ──

/** Every model the plan speaks of: on a bed, or one nothing can print. Left out ones aren't. */
const modelsIn = (p: Plan) => [...new Set([...p.beds.flatMap((b) => b.models.map((m) => m.shelf)), ...p.cant.map((c) => c.shelf)])]

/** "Five models, three printers." */
export function planHeadline(p: Plan): string {
  const n = modelsIn(p).length
  if (!n) return 'Nothing left to print.'
  const models = n === 1 ? 'One model' : `${Count(n)} models`
  if (!p.printers) return `${models}. No printer can take ${n === 1 ? 'it' : 'them'} now.`
  return `${models}, ${count(p.printers)} printer${p.printers === 1 ? '' : 's'}.`
}

export const RULE = 'Same filament shares a bed when it fits. Another filament goes to another printer. A busy one takes its turn.'

/** The beds with a printer, one card each; a bed waiting for any printer is a strip instead. */
export const cardsOf = (p: Plan) => p.beds.filter((b) => b.printer)

export type ChipTone = 'green' | 'gray' | 'blue' | 'amber'
/** The chip at a card's top right: when its printer takes it. A bed someone moved there says so. */
export function chipOf(b: PlanBed, picks: PlanPick[] = []): { word: string; tone: ChipTone } {
  const moved = !!b.printer && b.models.some((m) => { const p = picks.find((x) => x.shelf === m.shelf); return p?.printer === b.printer && p.bed !== 'own' })
  const k = b.when.kind
  if (moved && (k === 'now' || k === 'clear')) return { word: 'Moved here', tone: 'blue' }
  if (k === 'now') return { word: 'Free now', tone: 'green' }
  if (k === 'clear') return { word: 'Once its bed is clear', tone: 'green' }
  if (k === 'next') return { word: b.when.clock ? `Next, about ${b.when.clock}` : 'Next', tone: 'gray' }
  if (k === 'queued') return { word: 'After Up next', tone: 'gray' }
  if (k === 'after') return { word: `After bed ${b.order - 1}`, tone: 'gray' }
  return { word: 'Waits', tone: 'amber' }
}

/** The line under the printer's name, beside the filament's dot: "Gray PETG in slot 3", "Blue PLA · it asks what's
 *  loaded", "White PLA · printing a lid now". `job` is what the printer is printing, when it says. */
export function filamentLine(b: PlanBed, job?: string | null): string {
  if (b.asks) return `${b.words} · it asks what's loaded`
  if (b.when.kind === 'next') return `${b.words} · printing ${job ? `${lower(job)} ` : ''}now`
  return b.slot ? `${b.words} in slot ${b.slot}` : b.words
}

/** ONE BED, ITS NEXT BED, SECOND BED, AFTER THE FIRST. */
export function bedLabel(b: PlanBed): string {
  if (b.order > 1) return `${ORDINAL[b.order] ?? `Bed ${b.order}`} bed, after the ${lower(ORDINAL[b.order - 1] ?? 'one before')}`
  return b.when.kind === 'next' || b.when.kind === 'queued' ? 'Its next bed' : 'One bed'
}

/** A model's line on its card: its filament as last time, or how much of it this bed takes when it's split. */
export function modelLine(p: Plan, b: PlanBed, m: PlanModel): string {
  if (m.of > m.copies) {
    const all = p.beds.filter((x) => x.models.some((y) => y.shelf === m.shelf))
    const at = all.indexOf(b)
    return at > 0 && at === all.length - 1 ? `the other ${m.copies}` : `${m.copies} of ${m.of}`
  }
  return `${b.words}, ${m.chosen ? 'picked here' : m.first ? "what's loaded" : 'as last time'}`
}

/** The card's note, when there's more to say than its chip and line: it asks, it waits its turn, it couldn't be checked. */
export function noteOf(b: PlanBed): string {
  return b.when.kind === 'now' && !b.asks && b.fits !== null ? '' : b.why
}

/** Time · grams and when it's done, as far as they're known: a model never timed alone leaves them unknown. */
export function costOf(b: PlanBed): { cost: string; done: string } {
  return { cost: costWords(b.seconds, b.grams), done: b.done_at ? `done about ${clock(b.done_at)}` : '' }
}
export const UNTIMED = "Timed once it's set up"

/** A model nothing can print now, in amber: a bed that waits for any printer with its filament, or one the box can't
 *  plan (gone from the shelf, doesn't fit, a printer asked for that can't take it). `short` is the phone's line. */
export interface Strip { key: string; shelves: string[]; title: string; line: string; short: string; pictures: (string | null)[] }
const named = (m: { name: string | null; copies: number }) => `${m.name ?? 'A model'}${m.copies > 1 ? ` × ${m.copies}` : ''}`
export function stripsOf(p: Plan): Strip[] {
  return [
    ...p.beds.filter((b) => !b.printer).map((b) => ({
      key: b.id, shelves: b.models.map((m) => m.shelf), title: `${b.models.map(named).join(', ')} · ${b.words}`, line: b.why,
      short: `${b.models.length === 1 ? `The ${lower(b.models[0].name)} waits` : `${and(b.models.map((m) => m.name))} wait`}: ${b.words} isn't loaded anywhere.`,
      pictures: b.models.map((m) => m.picture) })),
    ...p.cant.map((c) => ({ key: `cant:${c.shelf}`, shelves: [c.shelf], title: named(c), line: c.why, short: `${named(c)}: ${c.why}`, pictures: [] as (string | null)[] })),
  ]
}

/** "Kobra 3 #2 and Desk are free too: none of these need them. Tap a model to move it." */
export function freeLine(p: Plan): string {
  const names = p.free_left.map((f) => f.name)
  const tap = cardsOf(p).length ? 'Tap a model to move it.' : ''
  if (!names.length) return tap
  return `${and(names)} ${names.length === 1 ? 'is' : 'are'} free too: none of these need ${names.length === 1 ? 'it' : 'them'}. ${tap}`.trim()
}

/** The foot: when it's all done, what happens next, and the button. Away it's added to the queue: nothing starts. */
export function footOf(p: Plan | null, away: boolean): { done: string; line: string; go: string; short: string; can: boolean } {
  const line = away ? 'Nothing starts until someone at home says each bed is clear.' : 'Each printer asks about its bed before it starts.'
  const add = away || (!!p && !p.printers)
  const short = add ? 'Add to the queue' : 'Print all'
  if (!p || p.checking) return { done: 'Working it out…', line: 'The box checks what fits each bed.', go: 'Working it out…', short: 'Working it out…', can: false }
  if (!p.beds.length) return { done: '', line: '', go: short, short, can: false }
  const done = p.done_at ? `All done about ${clock(p.done_at)}.` : ''
  return { done, line, go: add ? short : `Print all · ${p.printers} printer${p.printers === 1 ? '' : 's'}`, short, can: true }
}

// ── too much for one bed (C-edge) ──

export interface Split { printer: string; said: string; shelves: string[]; keep: string | null }
/** Each bed the box split: what it said, and "Keep them all on Workshop" unless the rest stays there already. */
export function splitsOf(p: Plan): Split[] {
  return p.beds.filter((b) => b.split && b.printer).map((b) => {
    const said = p.said.find((s) => s.startsWith(`Not all of it fits one bed on ${b.printer_name}:`)) ?? ''
    return { printer: b.printer!, said, shelves: b.models.map((m) => m.shelf), keep: /a second bed there/.test(said) ? null : `Keep them all on ${b.printer_name}` }
  }).filter((s) => s.said)
}

/** Keep them all on that printer: each of the bed's models asks for it, and what doesn't fit makes a second bed there. */
export function keepAll(picks: PlanPick[], s: Split): PlanPick[] {
  return picks.map((p) => (s.shelves.includes(p.shelf) ? setPick([p], p.shelf, { printer: s.printer, bed: undefined })[0] : p))
}

// ── moving a model (C-move) ──

export interface MoveOption { key: string; title: string; line: string; on: boolean; off: boolean; patch: Partial<PlanPick> }
const names = (ms: PlanModel[]) => and(ms.map((m) => lower(m.name)))

/** Where else a model can go: as the box planned it, each printer in printOn()'s order (the ones that can't, last, with
 *  why), and its own bed on the printer it's on. */
export function moveOptions(b: PlanBed, shelf: string, picks: PlanPick[], ps: BenchPrinter[], printable: Printable): MoveOption[] {
  const pick = picks.find((p) => p.shelf === shelf) ?? { shelf, copies: 1 }
  const others = b.models.filter((m) => m.shelf !== shelf)
  const boxs = !pick.printer && pick.bed !== 'own'
  const want: Filament = { key: `${b.material}${b.color ?? ''}`, material: b.material, color: b.color, name: b.words, on: [] }
  const fresh = !!b.models.find((m) => m.shelf === shelf)?.first
  const rows = anyLoaded(printOn(ps, want, printable), fresh, ps, printable).filter((r) => !(boxs && r.id === b.printer))
  const box: MoveOption = {
    key: 'box', on: boxs, off: false, patch: { printer: undefined, bed: undefined },
    title: boxs && b.printer_name ? `${b.printer_name}${others.length ? `, with the ${names(others)}` : ''}` : boxs ? 'Waits in Up next' : 'Where the box puts it',
    line: boxs ? (b.printer ? `${bedLabel(b)}, as the box planned it` : b.why) : 'The box works it out again',
  }
  const at = (r: (typeof rows)[number]): MoveOption =>
    ({ key: r.id, title: r.name, line: r.line, on: !boxs && pick.bed !== 'own' && pick.printer === r.id, off: !r.fits, patch: { printer: r.id, bed: undefined } })
  const own: MoveOption[] = b.printer && (others.length || pick.bed === 'own') ? [{
    key: 'own', title: `${b.printer_name}, its own bed`, on: pick.bed === 'own', off: false, patch: { printer: b.printer, bed: 'own' },
    line: others.length ? `After the ${names(others)}: ${b.printer_name} asks about its bed again` : 'It never shares a bed with the others',
  }] : []
  return [box, ...rows.filter((r) => r.fits).map(at), ...own, ...rows.filter((r) => !r.fits).map(at)]
}

export const filOf = (f: Filament): PlanFil =>
  ({ material: f.material, color: f.color, ...(f.preset ? { filament: f.preset, filament_name: f.name } : {}) })
/** Which of the choices a bed prints in: one of yours by its preset, else by material and color. */
export function filKeyOf(fils: Filament[], b: PlanBed): string | null {
  return (b.filament ? fils.find((f) => f.preset === b.filament && f.color === b.color) : null)?.key ?? filamentFor(fils, b.material, b.color)?.key ?? null
}

/** The In choices for a bed: what can be picked, and the one it prints in now first when that isn't among them (a Black ASA
 *  model when nothing has Black ASA loaded). */
export function inChoices(fils: Filament[], b: PlanBed): { fils: Filament[]; on: string } {
  const key = filKeyOf(fils, b)
  if (key) return { fils, on: key }
  const now: Filament = { key: 'now', material: b.material, color: b.color, name: b.filament_name ?? b.words, on: [] }
  return { fils: [now, ...fils], on: 'now' }
}

/** A model never printed isn't tied to a filament: any printer with something loaded can take it, in the filament loaded
 *  on the most printers that it has (plan.py, _fresh). */
function anyLoaded(rows: PrintOnRow[], fresh: boolean, ps: BenchPrinter[], printable: Printable): PrintOnRow[] {
  if (!fresh) return rows
  const ranked = filaments(ps)
  const out = rows.map((r) => {
    const name = ps.find((x) => x.id === r.id)?.name
    const f = !r.fits && !r.stopped && !printable[r.id]?.error && name ? ranked.find((x) => x.on.includes(name)) : null
    return f ? { ...r, fits: true, line: r.now ? `Prints in ${f.name}` : `Prints in ${f.name}, once it's free` } : r
  })
  return [...out.filter((r) => r.fits), ...out.filter((r) => !r.fits)]
}

/** Where a whole bed can go (Change printer on its card): the box's pick, then each printer in printOn()'s order. */
export function bedOptions(b: PlanBed, picks: PlanPick[], ps: BenchPrinter[], printable: Printable): MoveOption[] {
  const ours = picks.filter((p) => b.models.some((m) => m.shelf === p.shelf))
  const first = ours[0]?.printer
  const chosen = first && ours.every((p) => p.printer === first && p.bed !== 'own') ? first : undefined
  const want: Filament = { key: `${b.material}${b.color ?? ''}`, material: b.material, color: b.color, name: b.words, on: [] }
  const rows = anyLoaded(printOn(ps, want, printable), b.models.every((m) => m.first), ps, printable).filter((r) => chosen || r.id !== b.printer)
  const box: MoveOption = {
    key: 'box', on: !chosen, off: false, patch: { printer: undefined, bed: undefined },
    title: !chosen && b.printer_name ? b.printer_name : !chosen ? 'Waits in Up next' : 'Where the box puts it',
    line: !chosen ? (b.printer ? `${bedLabel(b)}, as the box planned it` : b.why) : 'The box works it out again',
  }
  const at = (r: (typeof rows)[number]): MoveOption =>
    ({ key: r.id, title: r.name, line: r.line, on: chosen === r.id, off: !r.fits, patch: { printer: r.id, bed: undefined } })
  return [box, ...rows.filter((r) => r.fits).map(at), ...rows.filter((r) => !r.fits).map(at)]
}

export function moveBed(picks: PlanPick[], b: PlanBed, patch: Partial<PlanPick>): PlanPick[] {
  const ids = b.models.map((m) => m.shelf)
  return picks.map((p) => (ids.includes(p.shelf) ? setPick([p], p.shelf, patch)[0] : p))
}

// ── the bed's picture: its models' pictures, copies times over, on a plate seen from above at an angle ──

export interface Spot { picture: string | null; x: number; y: number; size: number }
/** Where each copy sits on a plate w × h (a diamond), at most `most` of them, the models' copies dealt in turn. */
export function plateSpots(models: { picture: string | null; copies: number }[], w = 180, h = 72, most = 36): Spot[] {
  const left = models.map((m) => Math.max(0, m.copies))
  const deal: (string | null)[] = []
  while (deal.length < most && left.some((n) => n > 0)) {
    left.forEach((n, i) => { if (n > 0 && deal.length < most) { deal.push(models[i].picture); left[i]-- } })
  }
  const n = deal.length
  if (!n) return []
  const cols = Math.ceil(Math.sqrt(n)), rows = Math.ceil(n / cols)
  const size = Math.max(12, Math.min(34, (w * 0.62) / Math.max(cols, rows)))
  return deal.map((picture, i) => {
    const u = 0.18 + (0.64 * ((i % cols) + 0.5)) / cols
    const v = 0.18 + (0.64 * (Math.floor(i / cols) + 0.5)) / rows
    return { picture, x: Math.round(w / 2 + ((u - v) * w) / 2), y: Math.round(((u + v) * h) / 2), size: Math.round(size) }
  })
}

// ── how a bed prints (11 October 2026): the model page's How it prints, for every model on the bed ──

/** The how the box planned the bed with, and whether its models differ on their brim. */
export function bedHow(b: PlanBed): { how: How; mixed: boolean } {
  const mixed = b.brim === 'mixed'
  return { how: { purpose: (b.purpose || 'everyday') as Purpose, supports: (b.supports ?? null) as SupportKind | null,
                  brim: b.brim === 'mixed' ? null : b.brim ?? null, settings: { ...b.settings } }, mixed }
}

/** The card's How it prints line. */
export function bedHowLine(b: PlanBed, o: { purposes?: PurposeOption[] | null; editable?: Editable[] | null; usual?: SupportKind | null } = {}): string {
  const { how, mixed } = bedHow(b)
  return howLine(how, { ...o, mixed })
}

/** The bed's How it prints sheet: the model page's four tiles for its printer; a brim its models differ on is Mixed. */
export function bedTiles(b: PlanBed, o: { purposes?: PurposeOption[] | null; editable?: Editable[] | null; usual?: SupportKind | null } = {}): Tile[] {
  const { how, mixed } = bedHow(b)
  return howTiles(how, { ...o, printer: b.printer_name }).map((t) => (t.id === 'brim' && mixed ? { ...t, value: 'Mixed', line: 'Each model its own now' } : t))
}

/** A change on a bed's sheet is saved with every model on it, each by the model page's own PUT …/how. */
export function bedHowSaves(b: PlanBed, change: HowChange): { shelf: string; change: HowChange }[] {
  return [...new Set(b.models.map((m) => m.shelf))].map((shelf) => ({ shelf, change }))
}

/** The plan as it shows while the box plans again: each bed with any of these models, the change laid over its how. */
export function withHow(p: Plan, shelves: string[], change: HowChange): Plan {
  return { ...p, beds: p.beds.map((b) => {
    if (!b.models.some((m) => shelves.includes(m.shelf))) return b
    const { how, mixed } = bedHow(b)
    const h = mergeHow(how, change)
    return { ...b, purpose: h.purpose, supports: h.supports, settings: h.settings, brim: 'brim' in change ? h.brim : mixed ? 'mixed' : h.brim }
  }) }
}
