// Slicing like their prints (design/getting-started/, C, picked 5 October 2026; the contract with the printer's side
// is docs/slicer-profile.md). On a printer someone else set up, Elyir Bench slices with the profile their own
// OrcaSlicer files carry. Print says so once before the first model ("Slicing like your prints", c-slice-found),
// asks when the files disagree, offers newer settings on one line (c-slice-newer), and says what to do when no file
// carries any. The words and the rules for what shows when live here, pure, so tests/profile.test.ts can pin them
// to the boards; FoundSheet.vue, ProfilesSheet.vue and NewerCard.vue only draw them.

import { PRODUCT } from './setup.ts'

export type ProfileState = 'using' | 'ask' | 'none' | 'yours' | 'newer'

export interface ProfileMaterial { preset: string; files: number }
export interface ProfileChecks { bed_ok: boolean; bed_klipper?: number[] | null; start_ok: boolean }
/** One group of files that agree: the same machine, process, nozzle and bed. */
export interface FoundProfile {
  id: string
  printer: string
  process: string
  nozzle: number
  bed: number[]
  files: number
  slicer?: string | null
  /** The newest file's time, in seconds */
  newest: number
  materials: Record<string, ProfileMaterial>
  start?: string | null
  checks: ProfileChecks
}
/** GET /printer/intent/profile */
export interface ProfileInfo {
  state: ProfileState
  told: boolean
  using: string | null
  found: FoundProfile[]
  bed_klipper?: number[] | null
}

// ---- What shows when -------------------------------------------------------------------------

/** The profile it slices with, if any. */
export const inUse = (info: ProfileInfo | null): FoundProfile | null =>
  info?.found.find((p) => p.id === info.using) ?? null

/** What tapping Print a model opens before the model: the found sheet once, the list when the files disagree,
 *  or nothing (the file picker, as before). A printer that doesn't answer (null) slices as before. */
export function firstSheet(info: ProfileInfo | null): 'found' | 'ask' | null {
  if (!info) return null
  if (info.state === 'ask' && info.found.length) return 'ask'
  if (info.state === 'using' && !info.told && inUse(info)) return 'found'
  return null
}

/** No file carries a profile: slicing waits, and Print a model says why instead of opening anything. */
export const NONE_WORDS = `Slice one file in OrcaSlicer and print it, and ${PRODUCT} learns your settings from it.`
export const slicingWaits = (info: ProfileInfo | null) => info?.state === 'none'

/** Print a model's subtitle when it slices like their files (c-slice-newer: "sliced here like your prints"). */
export const LIKE_YOURS = 'Sliced like your prints.'
export const learned = (info: ProfileInfo | null) => (info?.state === 'using' || info?.state === 'newer') && !!inUse(info)

// ---- Words ---------------------------------------------------------------------------------------

const NUMBER_WORDS = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine']
const count = (n: number) => (n >= 0 && n < NUMBER_WORDS.length ? NUMBER_WORDS[n] : String(n))
const files = (n: number) => `${n} ${n === 1 ? 'file' : 'files'}`
/** "0.4 mm", "0.25 mm" */
export const mm = (n: number) => `${Number(n.toFixed(2))} mm`
/** "350 × 350" */
export const bedWords = (bed: number[] | null | undefined) => (bed && bed.length >= 2 ? `${Math.round(bed[0])} × ${Math.round(bed[1])}` : '')

/** "0.20mm Standard @Voron" → "Standard": the part a person calls it by. */
export function shortProcess(process: string): string {
  const s = process.replace(/^\s*\d+(\.\d+)?\s*mm\s+/i, '').replace(/\s*@.*$/, '').trim()
  return s || process
}

/** "Voron 2.4 350 0.6 nozzle" → "Voron 2.4 350": Orca names a machine by its nozzle too, which is said apart. */
export const printerName = (printer: string) => printer.replace(/\s+\d+(\.\d+)?\s*nozzle$/i, '').trim() || printer

/** The materials their files carry, most used first. */
export const materialsOf = (p: FoundProfile) =>
  Object.entries(p.materials).sort((a, b) => b[1].files - a[1].files || a[0].localeCompare(b[0])).map(([m]) => m)

/** What's loaded that their files don't cover: Orca's own preset for this printer slices those. */
export function otherMaterials(p: FoundProfile, loaded: (string | null | undefined)[]): string[] {
  const have = new Set(materialsOf(p).map((m) => m.toUpperCase()))
  const out: string[] = []
  for (const m of loaded) {
    const k = (m ?? '').trim().toUpperCase()
    if (k && !have.has(k) && !out.includes(k)) out.push(k)
  }
  return out
}

/** The materials row's note: "From your files. ASA: Orca's own for this printer." */
export function materialsNote(p: FoundProfile, loaded: (string | null | undefined)[]): string {
  const rest = otherMaterials(p, loaded)
  const who = rest.length ? rest.join(', ') : 'Others'
  return `${materialsOf(p).length ? 'From your files. ' : ''}${who}: Orca's own for this printer.`
}

/** A check that failed, in words; empty when the profile fits this printer. */
export function checkWords(p: FoundProfile, klipperBed?: number[] | null): string[] {
  const out: string[] = []
  const kb = p.checks.bed_klipper ?? klipperBed ?? null
  if (!p.checks.bed_ok) {
    out.push(kb ? `Made for a ${bedWords(p.bed)} bed; Klipper says this one is ${bedWords(kb)}.`
                : `Made for a ${bedWords(p.bed)} bed, which Klipper doesn't agree with.`)
  }
  if (!p.checks.start_ok && p.start) out.push(`Starts with ${p.start}, which Klipper here doesn't have.`)
  return out
}
export const fits = (p: FoundProfile) => p.checks.bed_ok && p.checks.start_ok

// ---- The found sheet (c-slice-found) -------------------------------------------------------------

export const FOUND_TITLE = 'Slicing like your prints'
export const PICK = 'Pick a model'

export interface SheetRow { label: string; value: string; note?: string; ok?: boolean; problem?: boolean }
export interface FoundView { title: string; sub: string; rows: SheetRow[]; button: string; others: string | null }

/** "Found in 15 of your files, made with OrcaSlicer 2.3. Nothing to set up." */
export function foundSub(p: FoundProfile): string {
  const made = p.slicer ? `, made with ${p.slicer}` : ''
  const n = p.files === 1 ? 'one' : String(p.files)
  return `Found in ${n} of your files${made}.${fits(p) ? ' Nothing to set up.' : ''}`
}

export function foundView(info: ProfileInfo, p: FoundProfile, loaded: (string | null | undefined)[]): FoundView {
  const kb = p.checks.bed_klipper ?? info.bed_klipper ?? null
  const bed = !p.checks.bed_ok
    ? { note: `${mm(p.nozzle)} nozzle · ${bedWords(p.bed)} bed; Klipper says ${bedWords(kb) || 'otherwise'}`, problem: true }
    : kb ? { note: `${mm(p.nozzle)} nozzle · ${bedWords(p.bed)} bed, as Klipper says`, ok: true }
         : { note: `${mm(p.nozzle)} nozzle · ${bedWords(p.bed)} bed` }
  const mats = materialsOf(p)
  const rows: SheetRow[] = [
    { label: 'Printer', value: printerName(p.printer), ...bed },
    { label: 'Settings', value: p.process },
    { label: 'Materials', value: mats.length ? mats.join(', ') : "Orca's own", note: materialsNote(p, loaded) },
  ]
  if (p.start) {
    rows.push(p.checks.start_ok
      ? { label: 'Starts with', value: p.start, note: "Your own macro, as your slicer's files do" }
      : { label: 'Starts with', value: p.start, note: "Klipper here doesn't have it", problem: true })
  }
  const others = info.found.length - 1
  return { title: FOUND_TITLE, sub: foundSub(p), rows, button: PICK, others: others > 0 ? `Other settings in your files (${others})` : null }
}

// ---- The list: ask, and the found sheet's other settings ---------------------------------------

export interface ListRow { id: string; title: string; line: string; chosen: boolean; problem: string | null }
export interface ListView { title: string; sub: string; rows: ListRow[] }

/** Each profile with its file count, most files first; what tells them apart is said on its second line. */
export function listRows(info: ProfileInfo): ListRow[] {
  const all = info.found
  const printers = new Set(all.map((p) => printerName(p.printer))).size > 1
  return [...all].sort((a, b) => b.files - a.files || b.newest - a.newest).map((p) => ({
    id: p.id,
    title: p.process,
    line: [printers ? printerName(p.printer) : null, `${mm(p.nozzle)} nozzle`, files(p.files)].filter(Boolean).join(' · '),
    chosen: p.id === info.using,
    problem: checkWords(p, info.bed_klipper)[0] ?? null,
  }))
}

/** ask: before the first slice. Otherwise: the found sheet's "Other settings in your files". */
export function listView(info: ProfileInfo, printer: string): ListView {
  const rows = listRows(info)
  if (info.state === 'ask') {
    return { title: `How do you slice for ${printer}?`, rows,
             sub: `Your files were sliced ${count(rows.length)} ways. ${PRODUCT} slices like the one you pick.` }
  }
  return { title: 'Settings in your files', rows, sub: `${PRODUCT} slices like the one you pick.` }
}

// ---- Newer prints (c-slice-newer) ----------------------------------------------------------------

export interface NewerOffer { id: string; text: string; ask: string; use: string; keep: string; problem: string | null }

/** What tells the newer profile apart from the one in use, as a person would say it. */
function differs(a: FoundProfile, b: FoundProfile): 'process' | 'nozzle' | 'printer' | null {
  if (a.process !== b.process) return 'process'
  if (a.nozzle !== b.nozzle) return 'nozzle'
  if (a.printer !== b.printer) return 'printer'
  return null
}

/** The newest profile newer than the one in use, offered on one line; never a switch. */
export function newerOffer(info: ProfileInfo | null): NewerOffer | null {
  if (!info || info.state !== 'newer') return null
  const cur = inUse(info)
  if (!cur) return null
  const next = info.found.filter((p) => p.id !== cur.id && p.newest > cur.newest).sort((a, b) => b.newest - a.newest)[0]
  if (!next) return null
  const how = differs(next, cur)
  const what = how === 'nozzle' ? `a ${mm(next.nozzle)} nozzle` : how === 'printer' ? next.printer : next.process
  const keep = how === 'nozzle' ? `Keep ${mm(cur.nozzle)}` : how === 'printer' ? `Keep ${cur.printer}` : `Keep ${shortProcess(cur.process)}`
  return { id: next.id, text: `Your newer prints use ${what}.`, ask: 'Slice like those from now on?', use: 'Use them', keep,
           problem: checkWords(next, info.bed_klipper)[0] ?? null }
}
