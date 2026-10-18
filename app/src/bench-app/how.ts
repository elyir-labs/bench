// How a model on the Bench Box's shelf prints (design/bench-how/, A, picked 6 October 2026; docs/bench-how.md): the
// printer's own choices (It's for, Supports, Brim, Every setting) kept with the model, so printing it again, queuing
// it and Whichever is free first all print it the same way. Pure, so tests/bench-how.test.ts can pin the words;
// ModelPage draws them.

import { BRIM_WORDS, KIND_WORDS, editWords, type Editable, type Purpose, type SupportKind } from '../slice/plan.ts'

export type BrimKind = 'auto' | 'none' | 'ears' | 'all'

/** What a model keeps (GET /bench/shelf `how`). null supports: the printer's usual; null brim: each part's own. */
export interface How {
  purpose: Purpose
  supports: SupportKind | null
  brim: BrimKind | null
  settings: Record<string, string>   // Orca key -> value, laid over the printer's own
}
/** A change to it (PUT …/how, or a slice's override): a setting set to null is removed. */
export type HowChange = Partial<Omit<How, 'settings'>> & { settings?: Record<string, string | null> }

export const DEFAULT_HOW: How = { purpose: 'everyday', supports: null, brim: null, settings: {} }

/** A shelf item's how, with the defaults filled in (a box that hasn't sent one yet, or only part of one). */
export function howOf(it: { how?: Partial<How> | null } | null | undefined): How {
  const h = it?.how ?? {}
  return { purpose: h.purpose ?? 'everyday', supports: h.supports ?? null, brim: h.brim ?? null, settings: { ...(h.settings ?? {}) } }
}

/** A change laid over a how, as the box does it: given fields replace, settings merge, a null setting is removed. */
export function mergeHow(how: How, change: HowChange): How {
  const settings = { ...how.settings }
  for (const [k, v] of Object.entries(change.settings ?? {})) {
    if (v == null) delete settings[k]
    else settings[k] = v
  }
  return {
    purpose: change.purpose ?? how.purpose,
    supports: 'supports' in change ? change.supports ?? null : how.supports,
    brim: 'brim' in change ? change.brim ?? null : how.brim,
    settings,
  }
}

/** The setup on the box is reused while none of this changed: printer, copies, filament, how, and which side down. */
export function setupKey(printer: string, copies: number, filament: string, how: How, sides = ''): string {
  const settings = Object.keys(how.settings).sort().map((k) => `${k}=${how.settings[k]}`).join(',')
  return [printer, copies, filament, how.purpose, how.supports ?? '', how.brim ?? '', settings, ...(sides ? [sides] : [])].join('|')
}

// the slicer's own words when its options haven't come yet (PURPOSES in slicer/elyir_bench_slice.py)
const PURPOSE_WORDS: Record<Purpose, { label: string; summary: string }> = {
  draft: { label: 'Quick draft', summary: 'Fast and light. Checking a fit, or a first try.' },
  everyday: { label: 'Everyday', summary: 'Good all round. The one to pick when unsure.' },
  display: { label: 'Looks best', summary: 'Fine layers and a tidy seam, for things people look at.' },
  strong: { label: 'Strong', summary: 'For parts that carry load: brackets, mounts, tools.' },
}
export interface PurposeOption { id: string; label: string; summary: string }

/** The four purposes, as the box's slicer names them. */
export function purposeList(options: PurposeOption[] | null | undefined): { id: Purpose; label: string; summary: string }[] {
  return (Object.keys(PURPOSE_WORDS) as Purpose[]).map((id) => {
    const o = options?.find((p) => p.id === id)
    return { id, label: o?.label ?? PURPOSE_WORDS[id].label, summary: o?.summary ?? PURPOSE_WORDS[id].summary }
  })
}

/** A brim's line on its tile: shorter than the sheet's. */
export const BRIM_TILE: Record<BrimKind, string> = {
  all: 'A rim to trim after',
  ears: 'Pads that snap off',
  none: 'Nothing to trim',
  auto: 'Orca decides as it slices',
}

export interface Tile { id: 'purpose' | 'supports' | 'brim' | 'settings'; label: string; value: string; line: string; link?: boolean }

/** "<Printer>'s usual", or the printer's when none is picked. */
export const usualOf = (printer: string | null | undefined) => (printer ? `${printer}'s usual` : "The printer's usual")

/** The Supports tile: the kind kept with the model, or the usual of the printer it would go to. */
export function supportsTile(how: How, usual: SupportKind | null, printer: string | null): { value: string; line: string } {
  if (how.supports) return { value: KIND_WORDS[how.supports].label, line: KIND_WORDS[how.supports].row }
  if (!usual) return { value: 'Usual', line: usualOf(printer) }
  return { value: KIND_WORDS[usual].label, line: `${KIND_WORDS[usual].row} · ${usualOf(printer)}` }
}

/** The Changed tile's value: "Nothing", the one setting ("Walls 4"), or how many ("3 settings"). */
export function changedWords(how: How, editable: Editable[]): string {
  const keys = Object.keys(how.settings)
  if (!keys.length) return 'Nothing'
  if (keys.length > 1) return `${keys.length} settings`
  const e = editable.find((x) => x.key === keys[0])
  return e ? `${e.label} ${editWords(e, how.settings[keys[0]])}` : '1 setting'
}

/** The four tiles under Print on, in the board's order (two columns: It's for, Supports; Brim, Changed). */
export function howTiles(how: How, o: { purposes?: PurposeOption[] | null; editable?: Editable[] | null; usual?: SupportKind | null; printer?: string | null }): Tile[] {
  const p = purposeList(o.purposes).find((x) => x.id === how.purpose) ?? purposeList(null)[1]
  const sup = supportsTile(how, o.usual ?? null, o.printer ?? null)
  const brim = how.brim ? { value: BRIM_WORDS[how.brim].label, line: BRIM_TILE[how.brim] } : { value: "Each part's own", line: 'As it last printed' }
  return [
    // the summary's first words fit a tile ("Good all round"); the sheet has the whole of it
    { id: 'purpose', label: "It's for", value: p.label, line: p.summary.split('.')[0] },
    { id: 'supports', label: 'Supports', ...sup },
    { id: 'brim', label: 'Brim', ...brim },
    { id: 'settings', label: 'Changed', value: changedWords(how, o.editable ?? []), line: 'Every setting', link: true },
  ]
}

/** "1 h 12 min", "48 min": a setup's time. */
export function minutes(seconds: number | null | undefined): string {
  if (seconds == null) return ''
  const m = Math.round(seconds / 60)
  if (m < 1) return 'under a minute'
  if (m < 60) return `${m} min`
  const h = Math.floor(m / 60), r = m % 60
  return r ? `${h} h ${r} min` : `${h} h`
}

/** "1 h 12 min · 21 g": what a setup costs. */
export function costWords(seconds: number | null | undefined, grams: number | null | undefined): string {
  return [minutes(seconds), grams != null ? `${Math.round(grams)} g` : ''].filter(Boolean).join(' · ')
}

/** The line under Print on's buttons: "About 1 h 12 min · 21 g on Desk". */
export function aboutLine(seconds: number | null | undefined, grams: number | null | undefined, printer: string): string {
  const cost = costWords(seconds, grams)
  return cost ? `About ${cost} on ${printer}` : ''
}

export interface SettingRow { key: string; label: string; help: string; now: string; mine: boolean; why: string }

/** Every setting: each one the model sets (its own), then the rest as the printer it would go to prints them. */
export function settingRows(editable: Editable[], how: How, values: Record<string, string> | null | undefined, printer: string | null): SettingRow[] {
  return editable.map((e) => {
    const mine = e.key in how.settings
    return { key: e.key, label: e.label, help: e.help, mine,
             now: editWords(e, mine ? how.settings[e.key] : values?.[e.key]),
             why: mine ? "This model's own" : printer ? `${printer}'s own` : "The printer's own" }
  })
}

/** The value a setting starts from in its control: the model's own, else as the printer prints it, else Orca's. */
export function settingValue(e: Editable, how: How, values: Record<string, string> | null | undefined): string {
  return how.settings[e.key] ?? values?.[e.key] ?? e.default
}

/** How it prints in one line, from the tiles' words, leaving out what's as usual: "Everyday · Tree supports",
 *  "Strong · Normal supports · Corner pads · Walls 4". `mixed`: the models it speaks for differ on their brim. */
export function howLine(how: How, o: { purposes?: PurposeOption[] | null; editable?: Editable[] | null; usual?: SupportKind | null; mixed?: boolean }): string {
  const p = purposeList(o.purposes).find((x) => x.id === how.purpose) ?? purposeList(null)[1]
  const kind = how.supports ?? o.usual ?? null
  const supports = kind === 'off' ? 'Supports off' : kind ? `${KIND_WORDS[kind].label} supports` : 'Usual supports'
  const brim = o.mixed ? 'Mixed brims' : how.brim ? BRIM_WORDS[how.brim].short : ''
  const n = Object.keys(how.settings).length
  const changed = n > 1 ? `${n} settings changed` : n ? changedWords(how, o.editable ?? []).replace(/^1 setting$/, '1 setting changed') : ''
  return [p.label, supports, brim, changed].filter(Boolean).join(' · ')
}
