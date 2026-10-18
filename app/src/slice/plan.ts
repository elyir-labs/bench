// Printing a model (design/print-a-model/, C "Ready first"): the decisions the screen makes before
// anyone asks. Pure functions only, so tests/slice.test.ts can pin them.

export type Purpose = 'draft' | 'everyday' | 'display' | 'strong'
export const PURPOSES: Purpose[] = ['draft', 'everyday', 'display', 'strong']

export interface SpoolLike {
  slot: number
  color: string | null
  material: string | null
  status: 'ready' | 'empty' | 'low' | 'unknown'
  in_use: boolean
  grams?: number | null
  name?: string | null
  direct?: boolean
}

export interface SliceChange {
  key: string
  label: string
  value: unknown
  was: unknown
  why: string
  source: 'purpose' | 'supports' | 'spool' | 'printer' | 'model' | 'kept' | 'you'
}

/** A setting a person may change (design/edit-settings/, C), as the slicer describes it (EDITABLE in
 *  slicer/elyir_bench_slice.py): a number with its range and step, or a choice of Orca values with people's names. */
export interface Editable {
  key: string
  label: string
  kind: 'number' | 'choice'
  min?: number
  max?: number
  step?: number
  unit?: string
  default: string
  choices?: [string, string][]
  help: string
}

/** A setting's value as people read it: "0.2 mm", "4", "25%", "4 layers", "All round". */
export function editWords(e: Editable, v: string | null | undefined): string {
  const s = String(v ?? e.default)
  if (e.kind === 'choice') return e.choices?.find(c => c[0] === s)?.[1] ?? s
  const n = parseFloat(s)
  if (Number.isNaN(n)) return s
  if (e.unit === '%') return `${n}%`
  return e.unit ? `${n} ${e.unit}` : `${n}`
}

/** A number setting's steps: its value as an index from min, the count, and back to Orca's text. */
export function steps(e: Editable, v: string | null | undefined): { at: number; last: number; value: (i: number) => string } {
  const min = e.min ?? 0, step = e.step ?? 1
  const last = Math.round(((e.max ?? min) - min) / step)
  const at = Math.max(0, Math.min(last, Math.round((parseFloat(String(v ?? e.default)) - min) / step)))
  return { at, last, value: i => `${+(min + i * step).toFixed(4)}${e.unit === '%' ? '%' : ''}` }
}

/** The person's changes in a few words, for a Ready row: "Walls 4 · Inside 25%". */
export function editSummary(editable: Editable[], set: Record<string, string> | null | undefined): string {
  return editable.filter(e => set && e.key in set).map(e => `${e.label} ${editWords(e, set![e.key])}`).join(' · ')
}

export interface EditRow { key: string; label: string; now: string; was: string; why: string }

/** Every editable setting for Every setting: kept for the purpose, set for this print, and the rest with the reason
 *  they are what they are (the purpose's, the spool's, or the printer's own). */
export function editRows(editable: Editable[], values: Record<string, string> | undefined, before: Record<string, string> | undefined,
  changes: SliceChange[], printerName: string): { kept: EditRow[]; you: EditRow[]; rest: EditRow[] } {
  const out = { kept: [] as EditRow[], you: [] as EditRow[], rest: [] as EditRow[] }
  for (const e of editable) {
    const mine = changes.filter(c => c.key === e.key)
    const you = mine.find(c => c.source === 'you'), kept = mine.find(c => c.source === 'kept')
    const other = mine.find(c => c.source !== 'you' && c.source !== 'kept')
    const row: EditRow = { key: e.key, label: e.label, now: editWords(e, values?.[e.key]), was: '', why: other?.why ?? `${printerName}'s own` }
    if (you) out.you.push({ ...row, was: editWords(e, kept ? String(kept.value) : before?.[e.key]), why: you.why })
    else if (kept) out.kept.push({ ...row, was: editWords(e, before?.[e.key]), why: kept.why })
    else out.rest.push(row)
  }
  return out
}

/** The spools a model can print from: loaded, and a material this printer has settings for. */
/** The spool a plate is sliced for: what it says is loaded, else PLA (or the first material it has settings for). */
export interface Choice { slot: number | null; material: string; color: string | null; name: string }
export function spoolChoice(s: SpoolLike | null, materials: string[]): Choice {
  if (s && s.material) {
    return { slot: s.direct ? null : s.slot, material: s.material.toUpperCase(), color: s.color, name: s.name || `${s.material}` }
  }
  const m = materials.includes('PLA') ? 'PLA' : materials[0]
  return { slot: null, material: m, color: null, name: m }
}

export function usableSpools<T extends SpoolLike>(spools: T[], materials: string[]): T[] {
  const known = new Set(materials.map(m => m.toUpperCase()))
  return spools.filter(s => (s.status === 'ready' || s.status === 'low') && !!s.material && known.has(s.material.toUpperCase()))
}

/** Which spool a new model starts with: the one in the head, else the first usable one. */
export function pickSpool<T extends SpoolLike>(spools: T[], materials: string[]): T | null {
  const ok = usableSpools(spools, materials)
  return ok.find(s => s.in_use) ?? ok[0] ?? null
}

/** The largest whole-percent scale (at most 100%) that fits the model on the bed as it lies.
 *  Mirrors fit_scale in slicer/elyir_bench_slice.py; 1 when it fits or a size is unknown. */
export function fitScale(size: number[] | null | undefined, bed: number[] | null | undefined, margin = 0.98): number {
  if (!size || !bed) return 1
  const [x, y, z] = size
  const bx = bed[0] * margin, by = bed[1] * margin, bz = bed[2] || Infinity
  const k = Math.min(1, x ? bx / x : 1, y ? by / y : 1, z ? bz / z : 1)
  return k >= 1 ? 1 : Math.floor(k * 100) / 100
}

/** The side that doesn't fit, in words: "It's 412 mm long and the bed is 350 mm". */
export function tooBigWords(size: number[], bed: number[], printer: string): string {
  const [x, y, z] = size
  if (bed[2] && z / bed[2] >= Math.max(x / bed[0], y / bed[1])) return `It's ${Math.round(z)} mm tall and ${printer} prints up to ${Math.round(bed[2])} mm`
  return x / bed[0] >= y / bed[1]
    ? `It's ${Math.round(x)} mm long and the bed is ${Math.round(bed[0])} mm`
    : `It's ${Math.round(y)} mm deep and the bed is ${Math.round(bed[1])} mm`
}

const ONOFF: Record<string, string> = { '1': 'on', '0': 'off' }

/** A setting's value as a person reads it: "5", "40%", "0.12 mm", "5 layers", "tree". */
export function showValue(key: string, v: unknown): string {
  if (v == null || v === '') return ''
  const s = Array.isArray(v) ? String(v[0] ?? '') : String(v)
  if (key === 'enable_support') return ONOFF[s] ?? s
  if (key === 'support_type') return s.replace(/\(auto\)$/, '').trim()
  if (key === 'layer_height') return `${s} mm`
  if (key === 'top_shell_layers' || key === 'bottom_shell_layers') return `${s} layers`
  if (key === 'filament_colour') return s.toUpperCase()
  return s
}

export interface ChangeGroup {
  title: string
  rows: { label: string; was: string; now: string; why: string; key: string; color?: string }[]
}

/** Every setting, in the order the board draws them: the purpose's, supports, then the spool and printer's. */
export function groupChanges(changes: SliceChange[], purposeLabel: string, printerName: string): ChangeGroup[] {
  const groups: [string, SliceChange['source'][]][] = [
    ['The model', ['model']],
    [`Because it's ${purposeLabel}`, ['purpose']],
    ['Supports', ['supports']],
    [`From the spool and ${printerName}`, ['spool', 'printer']],
  ]
  const out: ChangeGroup[] = []
  for (const [title, sources] of groups) {
    const rows = changes.filter(c => sources.includes(c.source)).map(c => ({
      label: c.label, key: c.key, why: c.why,
      was: showValue(c.key, c.was), now: showValue(c.key, c.value),
      color: c.key === 'filament_colour' ? showValue(c.key, c.value) : undefined,
    }))
    if (rows.length) out.push({ title, rows })
  }
  return out
}

/** The kind of support, the person's (design/supports/, A): it starts on the printer's usual. */
export type SupportKind = 'normal' | 'tree' | 'off'
export const SUPPORT_KINDS: SupportKind[] = ['normal', 'tree', 'off']
export const KIND_WORDS: Record<SupportKind, { label: string; line: string; row: string }> = {
  normal: { label: 'Normal', line: 'Blocks under each overhang. Snap off in one piece.', row: 'Comes off in blocks' },
  tree: { label: 'Tree', line: 'Branches that touch in a few spots. Fewer marks; can grip.', row: 'Branches' },
  off: { label: 'Off', line: 'Overhangs print in the air and may droop.', row: 'Overhangs print in the air' },
}

/** Brims (design/brim/, A): what each is called, in a part's line, and on its card. */
export const BRIM_WORDS: Record<'none' | 'ears' | 'all' | 'auto', { label: string; short: string; line: string }> = {
  all: { label: 'All round', short: 'Brim all round', line: 'A 5 mm rim all the way round. Holds best; trim the edge after.' },
  ears: { label: 'Corners only', short: 'Corner pads', line: 'Small pads at the sharp corners. They snap off by hand.' },
  none: { label: 'None', short: 'No brim', line: 'Nothing to trim. Fine for a part that sits low and wide.' },
  auto: { label: "Orca's own", short: "Orca's brim", line: 'Orca decides as it slices.' },
}

/** A kind from anywhere (a plate remembered before kinds: auto) as one of the three; auto is the usual. */
export function asKind(s: string | null | undefined, usual: SupportKind): SupportKind {
  return s === 'normal' || s === 'tree' || s === 'off' ? s : usual
}

/** The Supports row: the kind, and whether it's the usual one or for this print only. A slice that needed
 *  none says so. */
export function supportsWords(kind: SupportKind, added: boolean | null | undefined, usual: SupportKind): { value: string; note: string } {
  const w = KIND_WORDS[kind]
  if (kind === 'off') return { value: w.label, note: w.row }
  if (added === false) return { value: 'None needed', note: 'Nothing overhangs too far' }
  return { value: w.label, note: kind === usual ? `${w.row} · your usual` : `${w.row}, for this print` }
}

/** "phone-stand.stl" → "Phone stand"; "[a]_buildplate_bushing_x1_r1s.stl" → "Buildplate bushing".
 *  Mirrors display_name in slicer/elyir_bench_slice.py. */
export function modelName(filename: string): string {
  const stem = filename
    .replace(/\.(stl|obj|step|stp|3mf)$/i, '').replace(/\.(stl|obj)$/i, '')
    .replace(/^(?:\[[^\]]*\][\s_-]*)+/, '')
    .replace(/(?:[\s_-]+(?:x1c?|x1e|p1[ps]|a1m?|r1s?|mk[34]s?|bambu|bbl))+$/i, '')
    .replace(/[_-]+/g, ' ').trim()
  return stem ? stem[0].toUpperCase() + stem.slice(1) : filename
}

/** "5 bushings", "1 knife holder": only the last word changes. A name of more than two words isn't
 *  bent ("6 copies of buildplate bushing open"). Mirrors plural in the slicer. */
export function plural(name: string, n: number): string {
  const lower = name ? name[0].toLowerCase() + name.slice(1) : 'thing'
  const words = lower.split(' ')
  if (words.length > 2) return n === 1 ? `1 copy of ${lower}` : `${n} copies of ${lower}`
  if (n === 1) return `1 ${lower}`
  let w = words[words.length - 1]
  if (/(s|x|z|ch|sh)$/.test(w)) w += 'es'
  else if (/[^aeiou]y$/.test(w)) w = w.slice(0, -1) + 'ies'
  else w += 's'
  return `${n} ${[...words.slice(0, -1), w].join(' ')}`
}

// ── more than one on the plate (design/plate/, A) ──

export interface PartLike { name: string; copies: number }

/** What's on the plate, said once: "Mount", "6 bushings", "3 parts". */
export function plateLabel(parts: PartLike[]): string {
  if (parts.length === 1) return parts[0].copies === 1 ? modelName(parts[0].name) : plural(modelName(parts[0].name), parts[0].copies)
  const n = parts.reduce((a, p) => a + p.copies, 0)
  return `${n} parts`
}

const NUMBER_WORDS = ['no', 'one', 'two', 'three', 'four', 'five']

/** The Ready page's headline. plates: how many plates the slice made (more than one: it didn't all fit). */
export function plateHeadline(parts: PartLike[], state: 'done' | 'failed' | 'working', plates = 1, scalePct?: string): string {
  const what = plateLabel(parts)
  const many = parts.length > 1 || parts[0].copies > 1
  if (state === 'failed') return `${what} couldn't be sliced.`
  if (state === 'working') return `Getting ${what} ready…`
  if (plates > 1) return `${what}, on ${NUMBER_WORDS[plates] ?? plates} plates.`
  if (!many && scalePct) return `${what} is ready, at ${scalePct}.`
  return `${what} ${many ? 'are' : 'is'} ready to print.`
}

/** How many of each part didn't fit on the first plate, and how many did in all. */
export function overflow(parts: PartLike[], firstCounts: number[] | null | undefined): { fit: number; rest: number } {
  if (!firstCounts) return { fit: parts.reduce((a, p) => a + p.copies, 0), rest: 0 }
  const fit = firstCounts.reduce((a, n) => a + n, 0)
  const asked = parts.reduce((a, p) => a + p.copies, 0)
  return { fit, rest: Math.max(0, asked - fit) }
}

/** The slicer's printer for this one: the same name, or the only one there is. */
export function matchPrinter<T extends { id: string; name: string }>(printers: T[], name: string | null | undefined): T | null {
  const n = (name ?? '').toLowerCase()
  return printers.find(p => p.name.toLowerCase() === n || p.id.toLowerCase() === n) ?? (printers.length === 1 ? printers[0] : null)
}
