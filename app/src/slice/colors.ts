// Several colors on one plate (design/multi-color/, B, picked 21 October 2026): the Colors card. Each color
// is a spool from a slot of the filament unit, or swapped in by hand while the print waits. Pure functions,
// so tests/colors.test.ts can pin them.

import type { Choice, SpoolLike } from './plan'

/** One of the plate's colors. hand: swapped in by hand. A color with no slot that isn't by hand, on a printer
 *  with a unit, isn't loaded yet: it's sliced as by hand, and Print waits until it's sorted. */
export interface PlateSpool extends Choice { hand: boolean }
export type Purge = 'chute' | 'tower' | 'both' | 'swap'
export interface FileColor { color: string | null; material: string | null; used: boolean }
/** What the slicer says the colors did (slice_service.py, _colors). at: seconds into the print. */
export interface ColorChange { layer: number; at: number; to: number; hand: boolean; purge: number }
export interface ColorsResult {
  spools: { spool: number; parts: number[]; first: boolean; swaps: number[]; changes: number; painted?: number[]; heights?: number[] }[]
  changes: ColorChange[]
  hand_swaps: number
  unit_changes: number
  changes_seconds: number
  grams: number[]
}

export const PURGE_WORDS: Record<Purge, { label: string; line: string }> = {
  chute: { label: 'Purge chute', line: 'Out of the chute, off the plate.' },
  tower: { label: 'Tower', line: 'A small tower beside the model takes it.' },
  both: { label: 'Both', line: 'Pushed out, then a thin tower settles the nozzle. Crisper edges.' },
  swap: { label: 'At the swap', line: 'Pushed through when you swap, until the new color comes out clean.' },
}

const PALETTE = [
  ['White', '#F4F4F2'], ['Black', '#1C1C1E'], ['Gray', '#8A8D91'], ['Silver', '#C4C7CC'], ['Red', '#D32F2F'],
  ['Orange', '#FF8800'], ['Yellow', '#F5C542'], ['Green', '#2E9E4F'], ['Teal', '#14B8A6'],
  ['Blue', '#2563EB'], ['Navy', '#1E3A8A'], ['Purple', '#7C3AED'], ['Pink', '#EC4899'], ['Brown', '#8B5A2B'],
  ['Beige', '#E3D3B0'],
] as const
const SAME = 70                              // the intent layer's "same color" distance

function rgb(hex: string): number[] {
  return [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16))
}
export function distance(a: string | null | undefined, b: string | null | undefined): number {
  if (!a || !b || !/^#[0-9a-f]{6}$/i.test(a) || !/^#[0-9a-f]{6}$/i.test(b)) return Infinity
  const [x, y] = [rgb(a), rgb(b)]
  return Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2])
}

/** "Yellow": the nearest everyday name for a color. */
export function colorWord(hex: string | null | undefined): string {
  if (!hex) return 'Unknown'
  return PALETTE.reduce((best, c) => (distance(c[1], hex) < distance(best[1], hex) ? c : best), PALETTE[0])[0]
}

export const sameSpool = (a: Choice, b: Choice) => a.slot === b.slot && a.material === b.material && (a.color ?? '') === (b.color ?? '')

/** A 3MF's own colors, each from the loaded spool that matches it best (same material when the file says, within
 *  the "same color" distance), no spool used twice. The first takes the spool in the head when that matches.
 *  One that nothing matches isn't loaded: it keeps the file's color, and waits for a spool or a swap by hand. */
export function matchFileColors(colors: FileColor[], spools: SpoolLike[], materials: string[]): PlateSpool[] {
  const known = new Set(materials.map(m => m.toUpperCase()))
  const fallback = known.has('PLA') ? 'PLA' : materials[0] ?? 'PLA'
  const free = spools.filter(s => (s.status === 'ready' || s.status === 'low') && s.material && known.has(s.material.toUpperCase()))
  const taken = new Set<number>()
  return colors.map(c => {
    const material = c.material && known.has(c.material.toUpperCase()) ? c.material.toUpperCase() : null
    const fits = free.filter(s => !taken.has(s.slot) && (!material || s.material!.toUpperCase() === material) && distance(s.color, c.color) < SAME)
      .sort((a, b) => distance(a.color, c.color) - distance(b.color, c.color) || Number(b.in_use) - Number(a.in_use))
    const s = fits[0]
    if (s && c.used) {
      taken.add(s.slot)
      return { slot: s.direct ? null : s.slot, material: s.material!.toUpperCase(), color: s.color, name: s.name || s.material!, hand: false }
    }
    const m = material ?? fallback
    return { slot: null, material: m, color: c.color, name: `${colorWord(c.color)} ${m}`, hand: false }
  })
}

/** Not loaded and not by hand, on a printer with a unit: the color still needs a spool. */
export function unsorted(s: PlateSpool, unit: boolean): boolean {
  return unit && !s.hand && s.slot == null
}

/** "3 min", "3 and 8 min", "3, 8 and 27 min"; past four, "from 1 to 25 min": minutes into the print. */
export function minutesWords(at: number[]): string {
  const m = [...new Set(at.map(s => Math.max(1, Math.round(s / 60))))]
  if (m.length <= 1) return `${m[0] ?? 0} min`
  if (m.length > 4) return `from ${m[0]} to ${m[m.length - 1]} min`
  return `${m.slice(0, -1).join(', ')} and ${m[m.length - 1]} min`
}

const times = (n: number) => (n === 1 ? 'once' : n === 2 ? 'twice' : `${n} times`)
function at(swaps: number[]): string {
  const m = [...new Set(swaps.map(s => Math.max(1, Math.round(s / 60))))]
  return m.length > 4 ? `from about ${m[0]} to ${m[m.length - 1]} min` : `at about ${minutesWords(swaps)}`
}
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`

/** About how much plastic the purges push out (PLA, 1.75 mm): grams, from Orca's lengths. */
export function purgeGrams(c: ColorsResult): number {
  return c.changes.reduce((a, ch) => a + ch.purge, 0) * Math.PI * 0.875 ** 2 * 1.24 / 1000
}

/** The line at the foot of the Colors card: how many changes, who does them and when, and where the old color goes. */
export function costLine(c: ColorsResult, purge: Purge, unit: boolean): { strong: string; rest: string } {
  const swaps = c.changes.filter(ch => ch.hand).map(ch => ch.at)
  const g = purgeGrams(c)
  const where = purge === 'chute' ? `The old color goes out of the chute: ${g < 1 ? g.toFixed(1) : Math.round(g)} g.`
    : purge === 'tower' ? 'A tower beside the model takes the old color.'
    : purge === 'both' ? 'Pushed out, then a thin tower settles the nozzle.'
    : 'Each swap is pushed through until the new color comes out clean.'
  if (!c.changes.length) return { strong: 'No changes:', rest: 'each color prints on its own.' }
  if (!unit || c.unit_changes === 0) {
    return { strong: `You swap ${times(swaps.length)}, ${at(swaps)}.`, rest: 'The print waits at each one, and your phone is told.' }
  }
  if (swaps.length) {
    return { strong: `The unit does ${plural(c.unit_changes, 'change')}; you swap ${times(swaps.length)}, ${at(swaps)}.`, rest: where }
  }
  const first = c.changes[0].at
  const adds = Math.max(1, Math.round(c.changes_seconds / 60))
  const lead = c.changes.length === 1 ? `1 change, about ${Math.max(1, Math.round(first / 60))} min in, adds ${adds} min.`
    : `${plural(c.changes.length, 'change')} add about ${adds} min.`
  return { strong: lead, rest: where }
}

export const TOO_MANY = 10                   // more swaps by hand than anyone stands by for

/** Too many swaps by hand to stand by: how many, about how often, and over how long, in printing time (the
 *  changes' own time, which `at` counts in, left out). */
export function tooMany(c: ColorsResult | null | undefined): { count: number; every: number; over: number } | null {
  const all = c?.changes ?? []
  const each = all.length ? (c!.changes_seconds / all.length) : 0
  const t = all.map((ch, i) => ({ hand: ch.hand, t: ch.at - i * each })).filter(x => x.hand).map(x => x.t)
  if (t.length <= TOO_MANY) return null
  const over = t[t.length - 1] - t[0]
  return { count: t.length, every: Math.max(1, Math.round(over / (t.length - 1))), over }
}

/** "about one every 20 seconds for the first 20 minutes" */
export function tooManyWords(t: { count: number; every: number; over: number }): string {
  const every = t.every < 90 ? `${Math.round(t.every / 5) * 5 || 5} seconds` : `${Math.round(t.every / 60)} minutes`
  return `about one every ${every} for the first ${Math.max(1, Math.round(t.over / 60))} minutes`
}

/** The footer's line under the time. */
export function footColors(c: ColorsResult, n: number): string {
  const swaps = c.changes.filter(ch => ch.hand).map(ch => ch.at)
  if (swaps.length === 1) return `You're needed once, ${at(swaps)}`
  if (swaps.length) return `${swaps.length} swaps by hand`
  return `${n} colors · ${plural(c.changes.length, 'change')}`
}

const capital = (t: string) => t.charAt(0).toUpperCase() + t.slice(1)

/** A color's line on the card: where it comes from and what uses it. Without a unit, the color the slice starts
 *  with has to be in the printer: when that isn't the one loaded now (parts one after the other: Orca picks the
 *  order), its line says so. */
export function spoolLine(s: PlateSpool, k: number, c: ColorsResult | null, unit: boolean, uses: string): { text: string; amber: boolean } {
  const swaps = c?.spools[k]?.swaps ?? []
  if (unsorted(s, unit)) {
    return { text: `${uses ? `${uses} · ` : ''}Load it, swap it by hand, or pick another`, amber: true }
  }
  const first = c ? !!c.spools[k]?.first : k === 0
  if (!unit && first && k > 0) {
    return { text: capital([uses, 'it prints first: load it before you start'].filter(Boolean).join(' · ')), amber: true }
  }
  if (s.hand || (!unit && k > 0) || (!unit && !first)) {
    return { text: capital([uses, swaps.length ? `the print waits for you ${swaps.length > 4 ? `${swaps.length} times, ` : ''}${at(swaps)}` : 'swapped in by hand'].filter(Boolean).join(' · ')), amber: false }
  }
  const from = unit && s.slot != null ? `Slot ${s.slot + 1}` : 'In the printer now'
  return { text: [from, uses].filter(Boolean).join(' · '), amber: false }
}
