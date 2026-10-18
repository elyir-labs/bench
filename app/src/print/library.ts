// The Print tab's library (design/print-library/, direction B "a shelf and a door", chosen
// 3 October 2026): the printer's own files joined with its print history.
//
// The list comes from the files on the printer (server.files.get_directory), not from history,
// so a file sent from the slicer and never printed, or one printed long ago, is reachable. History
// only says how often and when. A file's time is the file's own estimate, never the last attempt's
// duration (which may be a failed print that lasted seconds). A past print whose file is gone
// stays on the shelf, honestly, until someone takes it off.
//
// Pure, so tests/print-library.test.ts can pin it; useLibrary.ts feeds it from Moonraker.
import { humanDuration, prettyName, usedColors, type JobMeta } from '../intent/jobs.ts'
import type { PrintCheck } from '../intent/types.ts'

export interface FileMeta extends JobMeta {
  estimated_time?: number
  slicer?: string
  modified?: number
}

/** A file under the gcodes root, path relative to it ("Voron spares/cube.gcode"). */
export interface PrinterFile {
  path: string
  modified: number
  meta: FileMeta | null
}

/** A server.history.list entry, the fields this needs. */
export interface PastJob {
  filename: string
  status: string
  start_time: number
  end_time?: number | null
  print_duration?: number | null
  metadata?: FileMeta | null
}

export interface Item {
  filename: string
  name: string
  folder: string | null
  /** The file's metadata, or for a file that's gone, the copy history kept. */
  meta: FileMeta | null
  /** When it arrived on the printer, in seconds. Null for a file that's gone. */
  modified: number | null
  /** Seconds: the file's own estimate. */
  estimate: number | null
  grams: number | null
  colors: string[]
  slicer: string | null
  /** Finished prints. */
  printed: number
  /** Every start, finished or not. */
  attempts: number
  lastPrinted: number | null
  /** The most recent start, for Recent's order. */
  lastJob: number | null
  onPrinter: boolean
}

export const DAY = 86400
export const SHELF_RECENT = 6
export const SHELF_NEW = 4
/** A never-printed file counts as New this long after it arrives. */
export const NEW_FOR_DAYS = 7

const folderOf = (path: string) => (path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : null)
const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : null)

/** Files joined with history: one item per file on the printer, plus one per past print whose file is gone. */
export function joinLibrary(files: PrinterFile[], jobs: PastJob[]): Item[] {
  const byFile = new Map<string, PastJob[]>()
  for (const j of jobs) {
    if (!j?.filename) continue
    const list = byFile.get(j.filename) ?? []
    list.push(j)
    byFile.set(j.filename, list)
  }
  const item = (filename: string, meta: FileMeta | null, modified: number | null, onPrinter: boolean): Item => {
    const past = (byFile.get(filename) ?? []).slice().sort((a, b) => b.start_time - a.start_time)
    const done = past.filter(j => j.status === 'completed')
    const lastDone = done[0]
    return {
      filename,
      name: prettyName(filename),
      folder: folderOf(filename),
      meta,
      modified,
      // the file's own estimate; history only when the file says nothing, and then only a finished print
      estimate: num(meta?.estimated_time) ?? num(lastDone?.print_duration),
      grams: num(meta?.filament_weight_total),
      colors: usedColors(meta),
      slicer: typeof meta?.slicer === 'string' && meta.slicer ? meta.slicer : null,
      printed: done.length,
      attempts: past.length,
      lastPrinted: lastDone ? (num(lastDone.end_time) ?? lastDone.start_time) : null,
      lastJob: past[0]?.start_time ?? null,
      onPrinter,
    }
  }
  const out: Item[] = []
  const here = new Set<string>()
  for (const f of files) {
    here.add(f.path)
    out.push(item(f.path, f.meta, num(f.modified) ?? num(f.meta?.modified), true))
  }
  for (const [filename, past] of byFile) {
    if (here.has(filename)) continue
    const newest = past.reduce((a, b) => (b.start_time > a.start_time ? b : a))
    out.push(item(filename, newest.metadata ?? null, null, false))
  }
  return out
}

export function isNew(i: Item, now: number): boolean {
  return i.onPrinter && i.attempts === 0 && i.modified != null && now - i.modified < NEW_FOR_DAYS * DAY
}

/** Everything on the printer, newest first. */
export function onPrinter(items: Item[]): Item[] {
  return items.filter(i => i.onPrinter).sort((a, b) => (b.modified ?? 0) - (a.modified ?? 0))
}

export interface Shelf {
  /** Sent from the slicer, not printed yet, newest first. */
  fresh: Item[]
  /** The last few things printed, newest first; a file that's gone stays unless taken off. */
  recent: Item[]
  /** How many files are on the printer. */
  total: number
  /** Three pictures for the way into the library: files that aren't on the shelf. */
  peek: Item[]
}

export function shelf(items: Item[], now: number, hidden: string[] = []): Shelf {
  const hide = new Set(hidden)
  const fresh = onPrinter(items).filter(i => isNew(i, now)).slice(0, SHELF_NEW)
  const recent = items
    .filter(i => i.lastJob != null && (i.onPrinter || !hide.has(i.filename)))
    .sort((a, b) => (b.lastJob ?? 0) - (a.lastJob ?? 0))
    .slice(0, SHELF_RECENT)
  const shown = new Set([...fresh, ...recent].map(i => i.filename))
  const all = onPrinter(items)
  const pictured = (i: Item) => !!i.meta?.thumbnails?.some(t => t.relative_path)
  const peek = all.filter(i => !shown.has(i.filename) && pictured(i)).slice(0, 3)
  return { fresh, recent, total: all.length, peek }
}

// ---- the library's filters --------------------------------------------------------------

export type Filter = null | 'fits' | 'never' | 'before' | 'hour' | `folder:${string}`

export interface Chip {
  id: Exclude<Filter, null>
  label: string
  count?: number
  folder?: boolean
}

export function chips(items: Item[]): Chip[] {
  const out: Chip[] = [
    { id: 'fits', label: "Fits what's loaded" },
    { id: 'never', label: 'Never printed' },
    { id: 'before', label: 'Printed before' },
    { id: 'hour', label: 'Under an hour' },
  ]
  const folders = new Map<string, number>()
  for (const i of onPrinter(items)) if (i.folder) folders.set(i.folder, (folders.get(i.folder) ?? 0) + 1)
  for (const [name, count] of [...folders].sort((a, b) => a[0].localeCompare(b[0]))) {
    out.push({ id: `folder:${name}`, label: name, count, folder: true })
  }
  return out
}

/** Does this file pass the filter? A file whose check hasn't come back yet counts as fitting. */
export function passes(i: Item, filter: Filter, check?: PrintCheck | null): boolean {
  if (!filter) return true
  if (filter === 'fits') return !check || check.ok
  if (filter === 'never') return i.printed === 0
  if (filter === 'before') return i.printed > 0
  if (filter === 'hour') return i.estimate != null && i.estimate < 3600
  const folder = filter.slice('folder:'.length)
  return i.folder === folder || !!i.folder?.startsWith(folder + '/')
}

export function searched(i: Item, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  return i.name.toLowerCase().includes(q) || i.filename.toLowerCase().includes(q)
}

export function filtered(items: Item[], filter: Filter, query: string, checks: Record<string, PrintCheck> = {}): Item[] {
  return onPrinter(items).filter(i => passes(i, filter, checks[i.filename]) && searched(i, query))
}

const files = (n: number) => `${n} ${n === 1 ? 'file' : 'files'}`

/** Beside the title: "23 files", "17 of 23 fit". */
export function countLabel(shown: number, total: number, filter: Filter, query = ''): string {
  if (query.trim()) return `${shown} of ${total} match`
  switch (filter) {
    case null: return files(total)
    case 'fits': return `${shown} of ${total} fit`
    case 'never': return `${shown} of ${total} never printed`
    case 'before': return `${shown} of ${total} printed before`
    case 'hour': return `${shown} of ${total} under an hour`
    default: return `${files(shown)} in ${filter.slice('folder:'.length)}`
  }
}

/** Above the grid on a phone: "23 files, newest first", "3 never printed, newest first". */
export function listLine(shown: number, filter: Filter, query = ''): string {
  if (query.trim()) return `${shown} ${shown === 1 ? 'matches' : 'match'} “${query.trim()}”, newest first`
  switch (filter) {
    case null: return `${files(shown)}, newest first`
    case 'fits': return `${shown} fit what's loaded, newest first`
    case 'never': return `${shown} never printed, newest first`
    case 'before': return `${shown} printed before, newest first`
    case 'hour': return `${shown} under an hour, newest first`
    default: return `${files(shown)} in ${filter.slice('folder:'.length)}, newest first`
  }
}

/** When a filter or a search leaves nothing. */
export function emptyLine(filter: Filter, query: string, printer: string): string {
  if (query.trim()) return `Nothing on ${printer} is called “${query.trim()}”.`
  switch (filter) {
    case 'fits': return `Nothing on ${printer} fits what's loaded right now.`
    case 'never': return `Everything on ${printer} has been printed at least once.`
    case 'before': return `Nothing on ${printer} has been printed yet.`
    case 'hour': return `Nothing on ${printer} takes under an hour.`
    default: return `Nothing on ${printer} yet. Send a file from your slicer and it shows up here, under New.`
  }
}

// ---- words ----------------------------------------------------------------------------

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']

/** "5 min ago", "3 hours ago", "yesterday", "5 days ago", "2 weeks ago", "in December". */
export function ago(t: number, now: number): string {
  const s = Math.max(0, now - t)
  const m = Math.round(s / 60)
  if (m < 1) return 'just now'
  if (m < 60) return `${m} min ago`
  const then = new Date(t * 1000), today = new Date(now * 1000)
  const midnight = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
  const days = Math.round((midnight(today) - midnight(then)) / (DAY * 1000))
  if (days === 0) { const h = Math.round(s / 3600); return h === 1 ? 'an hour ago' : `${h} hours ago` }
  if (days === 1) return 'yesterday'
  if (days < 7) return `${days} days ago`
  if (days < 14) return '1 week ago'
  if (days < 35) return `${Math.floor(days / 7)} weeks ago`
  return then.getFullYear() === today.getFullYear() ? `in ${MONTHS[then.getMonth()]}` : `in ${MONTHS[then.getMonth()]} ${then.getFullYear()}`
}

/** "14 September", with the year when it isn't this one. */
export function day(t: number, now: number): string {
  const d = new Date(t * 1000)
  const year = d.getFullYear() === new Date(now * 1000).getFullYear() ? '' : ` ${d.getFullYear()}`
  return `${d.getDate()} ${MONTHS[d.getMonth()]}${year}`
}

/** The slicer as people call it in "Sent from Orca". */
export function slicerShort(s: string | null): string | null {
  if (!s) return null
  if (/^orca/i.test(s)) return 'Orca'
  if (/^bambu/i.test(s)) return 'Bambu Studio'
  return s
}

const times = (n: number) => (n === 1 ? 'once' : `${n} times`)

/** "1 h 12 m · 38 g". */
export function metaLine(i: Item): string {
  return [humanDuration(i.estimate), i.grams != null ? `${Math.round(i.grams)} g` : ''].filter(Boolean).join(' · ')
}

/** A New card's first line: "Sent from Orca · 5 min ago". */
export function sentLine(i: Item, now: number): string {
  const when = i.modified != null ? ago(i.modified, now) : ''
  const from = slicerShort(i.slicer)
  return from ? `Sent from ${from}${when ? ` · ${when}` : ''}` : `Sent ${when}`.trim()
}

export interface TileLine { text: string; tone: 'need' | 'new' | '' }

/** A tile's third line: what's in the way first, then (in the library) what's new about it, then its history. */
export function tileLine(i: Item, check: PrintCheck | null | undefined, where: 'shelf' | 'library', now: number): TileLine | null {
  if (!i.onPrinter) return null
  if (check && !check.ok && !check.ask && check.short) return { text: check.short, tone: 'need' }
  if (where === 'shelf') return null
  if (isNew(i, now)) return { text: `New · sent ${ago(i.modified!, now)}`, tone: 'new' }
  if (i.folder) return { text: `in ${i.folder}`, tone: '' }
  if (i.printed > 0) return { text: `Printed ${times(i.printed)}`, tone: '' }
  return { text: i.attempts > 0 ? 'Never finished' : 'Never printed', tone: '' }
}

export interface SheetHistory {
  /** "Printed 3 times, last 5 days ago." */
  printed: string
  /** "From PrusaSlicer, on Workshop since 14 September." */
  from: string
  /** On a phone: "From PrusaSlicer." */
  fromShort: string
}

export function sheetHistory(i: Item, printer: string, now: number): SheetHistory {
  let printed: string
  if (i.printed > 0 && i.lastPrinted != null) {
    printed = i.printed === 1 ? `Printed once, ${ago(i.lastPrinted, now)}.` : `Printed ${i.printed} times, last ${ago(i.lastPrinted, now)}.`
  } else if (i.attempts > 0) {
    printed = `Started ${times(i.attempts)}, never finished.`
  } else {
    printed = 'Never printed.'
  }
  const slicer = i.slicer
  let where = ''
  if (i.modified != null) {
    where = now - i.modified < NEW_FOR_DAYS * DAY ? `sent ${ago(i.modified, now)}` : `on ${printer} since ${day(i.modified, now)}`
  }
  const from = slicer
    ? `From ${slicer}${where ? `, ${where}` : ''}.`
    : where ? `${where.charAt(0).toUpperCase()}${where.slice(1)}.` : ''
  return { printed, from, fromShort: slicer ? `From ${slicer}.` : '' }
}

// ---- taking things off the shelf ---------------------------------------------------------

/** The names taken off Recent (elyir-bench/print_hidden), newest last, without repeats. */
export function hide(hidden: string[], filename: string, keep = 200): string[] {
  return [...hidden.filter(h => h !== filename), filename].slice(-keep)
}

/** A removed tile stays where it was, drained, until nobody is looking; then the grid closes up. */
export interface Ghost { item: Item; index: number }

export function withGhosts(list: Item[], ghosts: Ghost[]): Item[] {
  const out = list.filter(i => !ghosts.some(g => g.item.filename === i.filename))
  for (const g of [...ghosts].sort((a, b) => a.index - b.index)) out.splice(Math.min(g.index, out.length), 0, g.item)
  return out
}
