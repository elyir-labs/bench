// Spool tags (design/spool-tags/, round 1 C + round 2 A/A/A): a tag held on the reader asks which spool it's for,
// on whatever screen is open. The printer (printer/spool_tags.py) holds the steps; this is the words and the order.

export type TagStep = 'which' | 'library' | 'write' | 'formats' | 'written' | 'read' | 'unknown' | 'copy' | 'failed'

export interface TagChoice {
  kind: 'slot' | 'history'
  slot?: number
  index?: number
  label: string
  color: string | null
  sub: string
}

export interface TagFormatRow { id: string; name: string; why_not: string | null; readers: string }

export interface TagSheetView {
  step: TagStep
  tag: { chip: string; blank: boolean; uid: string } | null
  choices?: TagChoice[]
  spool?: Record<string, unknown>
  label?: string
  facts?: string[]
  color?: string
  format?: string | null
  format_name?: string
  readers?: string
  formats?: TagFormatRow[]
  waiting?: boolean
  writing: boolean
  why?: string
  over?: boolean
}

export interface IntentTags {
  reader: { name: string | null; state: 'ready' | 'missing' | 'error'; why: string | null } | null
  sheet: TagSheetView | null
}

export interface LibraryColor { name: string; hex: string; weights: number[]; hit: boolean }
export interface LibraryProduct {
  id: number
  brand: string
  material: string
  line: string
  nozzle: [number, number] | null
  bed: [number, number] | null
  colors: LibraryColor[]
}

/** Up to this many quick answers before "Another spool": two rows on the 7" panel, as drawn. The rest are under
 *  Here now in the library. */
export const QUICK_CHOICES = 3

/** The quick answers: spools in the slots first, then ones written here before. */
export function quickChoices(choices: TagChoice[] | undefined): TagChoice[] {
  const all = choices ?? []
  return [...all.filter((c) => c.kind === 'slot'), ...all.filter((c) => c.kind === 'history')].slice(0, QUICK_CHOICES)
}

/** A product's name in a row: "PolyLite PETG", or "ELEGOO PLA" when the library has no line for it. */
export function productName(p: Pick<LibraryProduct, 'brand' | 'material' | 'line'>): string {
  const line = p.line.trim()
  if (!line) return `${p.brand} ${p.material}`
  return line.toLowerCase().includes(p.material.toLowerCase()) ? line : `${line} ${p.material}`
}

/** Who reads a written tag: "Anycubic ACE: every ACE here reads it." */
export function readersLine(formatName: string | undefined, readers: string | undefined): string {
  if (!formatName) return ''
  return readers ? `${formatName}: ${readers}.` : `${formatName}.`
}

/** The small line above the question: what's on the reader. */
export function chipLine(tag: TagSheetView['tag']): string {
  if (!tag) return 'Put the tag back on the reader'
  return tag.blank ? `Blank ${tag.chip}` : tag.chip
}

export function swatch(hex: string | null | undefined): string {
  const h = (hex ?? '').replace('#', '')
  return /^[0-9a-fA-F]{6}$/.test(h) ? `#${h}` : 'transparent'
}
