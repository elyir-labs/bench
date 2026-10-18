// What's being got ready to print (design/print-a-model/, C "Ready first"; design/plate/, A "the plate
// is a list"). The plate is a list of parts, each with its own count, size and way down; purpose, spool
// and supports are the whole plate's. It's sliced as soon as it's picked: the chosen purpose first, then
// the other three, so the purpose sheet can show what each one costs. Any change slices all four again.
//
// Which side down (design/orientation/, A, then any side): a part whose flattest side isn't down is laid
// on it for the person, and its sheet lists every side it can rest on, to put another one down.
//
// Normal or tree (design/supports/, A): a plate starts on the person's usual kind of support (kept in
// Moonraker, else the kind the printer's preset prints). Opening the Supports sheet slices the other two
// kinds for the chosen purpose, so each card shows its real supports and time; picking one keeps that slice.
//
// A setting changed (design/edit-settings/, C): for this print, or kept for every print of that purpose on this
// printer (Moonraker, beside the usual support). Kept ones go to the slicer with their purpose, this print's with all.
//
// Take parts off (design/remove-parts/, C): a file of several parts opens on a picker before anything is sliced;
// parts left off wait beside the plate (session.left) so "Change" can put them back. A part taken off the plate
// can be put back (Undo), and the plate is sliced once the taps stop.

import { computed, markRaw, reactive } from 'vue'
import * as api from './api'
import { asKind, fitScale, matchPrinter, pickSpool, PURPOSES, spoolChoice, SUPPORT_KINDS, type Choice, type Purpose, type SpoolLike, type SupportKind } from './plan'
import { compose, pickFrom, provisional, severalFrom, type Placed } from './plate'
import type { SupportLines } from './supports'
import { layOn, parseModel, sizeOf } from './stl'
import { thumbnail } from './render'

export type { Choice }
export { spoolChoice }
export type Lay = 'file' | 'flat' | 'side'

export interface Part {
  key: number
  name: string                               // the file's name
  model: string | null                       // the slicer's id for it, once uploaded
  trisFile: Float32Array | null              // as the file has it; markRaw: tens of thousands of numbers
  tris: Float32Array | null                  // the way it will print (laid flat or not), before resizing
  sizeFile: number[] | null
  size: number[] | null                      // the way it will print, before resizing
  lying: api.Lying | null
  lay: Lay
  layAuto: boolean                           // laid flat by the app, not the person
  down: number[] | null                      // lay 'side': the side the person put down
  brim: api.BrimAsk                          // auto: picked by the slicer from its shape (design/brim/, A)
  scale: number
  fit: number                                // the scale chosen for it when it didn't fit
  copies: number
  fill: (api.FitAnswer & { for: string }) | null   // how many fit ("Fill the plate"), for the plate as it was asked
  from: string                               // the file it came from
  order: number                              // its place in that file
}

export const session = reactive({
  stage: 'idle' as 'idle' | 'reading' | 'ready' | 'error',
  error: '',
  errorInfo: null as Record<string, any> | null,   // with the error: {off, slicer} when the slicer elsewhere is off
  parts: [] as Part[],
  files: [] as string[],                     // the files picked (a 3MF brings several parts)
  left: [] as Part[],                        // read from a file but not on the plate (design/remove-parts/, C)
  picking: null as { from: string; first: boolean } | null,   // the picker, for one file's parts
  undo: null as { part: Part; at: number } | null,            // the part last taken off, until Undo goes
  pending: false,                            // changed, slicing once the taps stop: the last slice's price is old
  adding: 0,                                 // files being read and uploaded after the first
  options: null as api.SliceOptions | null,
  printer: null as api.PrinterOption | null,
  purpose: 'everyday' as Purpose,
  supports: 'normal' as SupportKind,
  usual: 'normal' as SupportKind,            // the person's usual kind on this printer
  settings: {} as Record<string, string>,    // changed for this print
  kept: {} as Partial<Record<Purpose, Record<string, string>>>,   // changed for good, per purpose
  spool: null as Choice | null,
  spoolAuto: true,                           // chosen by the app, not the person: may follow the printer
  jobs: {} as Partial<Record<Purpose, api.SliceJob>>,
  jobFor: '',
  kinds: {} as Partial<Record<SupportKind, api.SliceJob>>,   // the other kinds, for the chosen purpose (the sheet)
  kindsFor: '',
  lines: {} as Record<string, SupportLines | null>,          // each slice's supports, by job id, once fetched
  placed: null as { for: string; at: Placed[] } | null,   // where Orca put things, last time it said
  sent: null as string | null,
  sentLater: [] as string[],
})

let generation = 0
let timer = 0
let soon = 0
let nextKey = 1

function unfinished(j: api.SliceJob | null | undefined): j is api.SliceJob {
  return !!j?.id && (j.state === 'queued' || j.state === 'slicing')
}

/** Stop the slicer working on anything this screen won't show: on a printer's Pi each one is seconds. */
function dropUnfinished() {
  for (const j of [...Object.values(session.jobs), ...Object.values(session.kinds)]) if (unfinished(j)) void api.cancelJob(j.id)
}

type Call = <T = unknown>(method: string, params?: Record<string, unknown>) => Promise<T>
let moonraker: Call | null = null
const USUAL = { namespace: 'elyir-bench', key: 'slice_usual' }

/** The printer's Moonraker, where the person's usual support is kept. */
export function useMoonraker(call: Call) { moonraker = call }

interface Usual { supports?: string; purposes?: Partial<Record<Purpose, Record<string, string>>> }

async function loadUsual(fallback: SupportKind): Promise<{ supports: SupportKind; kept: Usual['purposes'] }> {
  try {
    const r = await moonraker?.<{ value?: Usual }>('server.database.get_item', USUAL)
    const kept = r?.value?.purposes && typeof r.value.purposes === 'object' ? r.value.purposes : {}
    return { supports: asKind(r?.value?.supports, fallback), kept }
  } catch {
    return { supports: fallback, kept: {} }  // nothing kept yet
  }
}

const saveUsual = () =>
  moonraker?.('server.database.post_item', { ...USUAL, value: { supports: session.usual, purposes: session.kept } }).catch(() => undefined)

/** "Make Tree my usual": every plate on this printer starts on it from now on. */
export async function makeUsual(): Promise<void> {
  const k = session.supports
  if (k === 'off') return
  session.usual = k
  await saveUsual()
}

/** What a setting is asked to be now: this print's, else kept for the purpose, else what the purpose gives. */
export function wanted(key: string): string | undefined {
  return session.settings[key] ?? session.kept[session.purpose]?.[key] ?? current.value?.before?.[key]
}
/** Whether a changed setting is kept for the purpose (rather than for this print). */
export const isKept = (key: string) => !(key in session.settings) && key in (session.kept[session.purpose] ?? {})

/** A setting changed on Every setting: for this print, or kept for every print of this purpose. Asking for what it
 *  would be anyway takes the change away. Sliced once the taps stop. */
export function setSetting(key: string, value: string, scope: 'print' | 'keep') {
  const p = session.purpose, before = current.value?.before?.[key]
  const kept = { ...(session.kept[p] ?? {}) }
  const settings = { ...session.settings }
  delete settings[key]
  if (scope === 'keep') {
    if (value === before) delete kept[key]
    else kept[key] = value
    session.kept = { ...session.kept, [p]: kept }
    void saveUsual()
  } else {
    if (value !== (kept[key] ?? before)) settings[key] = value
  }
  session.settings = settings
  sliceSoon()
}

/** Move a change between this print and kept, keeping its value. */
export function setScope(key: string, scope: 'print' | 'keep') {
  const v = wanted(key)
  if (v == null) return
  if (scope === 'print' && key in (session.kept[session.purpose] ?? {})) {
    const kept = { ...session.kept[session.purpose] }
    delete kept[key]
    session.kept = { ...session.kept, [session.purpose]: kept }
    void saveUsual()
    session.settings = { ...session.settings, [key]: v }
    sliceSoon()
  } else if (scope === 'keep') setSetting(key, v, 'keep')
}

/** "Back to Elyir Bench's Everyday": the purpose's own settings again, for good. */
export function resetPurpose(p: Purpose = session.purpose) {
  const kept = { ...session.kept }
  delete kept[p]
  session.kept = kept
  void saveUsual()
  void sliceAll()
}

export const current = computed(() => session.jobs[session.purpose] ?? null)
/** The only part, when there's one: the page then reads as it did before plates (design/print-a-model/). */
export const only = computed(() => (session.parts.length === 1 ? session.parts[0] : null))
export const canLay = (p: Part | null | undefined) => !!p?.lying?.flat_better
export const tooBig = (p: Part | null | undefined) => !!p && p.scale < 1

/** What's on the plate, as the slicer sees it: a change to any of it makes the slices stale. */
export function plateKey(parts: Part[] = session.parts, skipCopiesOf = -1): string {
  return JSON.stringify(parts.map((p, i) => [p.model, i === skipCopiesOf ? 0 : p.copies, p.scale, p.lay, p.down, p.brim]))
}

/** Every copy of every part, where Orca put it (or, until it has, in rows in the middle of the bed). */
export const plate = computed(() => {
  const parts = session.parts.map(p => ({ tris: p.tris, copies: p.copies, scale: p.scale }))
  const key = plateKey()
  const at = session.placed?.for === key ? session.placed.at : provisional(parts, session.printer?.bed)
  return markRaw(compose(parts, at))
})


/** The side that goes down: the outward normal, or null for the file's own bottom. */
export function downOf(p: Part, lay: Lay = p.lay, down: number[] | null = p.down): number[] | null {
  return lay === 'side' ? down : lay === 'flat' ? p.lying?.flat_normal ?? null : null
}

const same = (a: number[], b: number[]) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2] > 0.996

function sizeFor(p: Part, normal: number[] | null): number[] | null {
  if (!normal) return p.sizeFile
  return p.lying?.sides?.find(s => same(s.normal, normal))?.size ?? (normal === p.lying?.flat_normal ? p.lying?.size_flat ?? null : null)
    ?? (p.tris ? sizeOf(p.tris) : p.sizeFile)
}

/** The part as it will print, and its size and fit on the bed. */
function applyLay(p: Part, lay: Lay, down: number[] | null = null) {
  p.lay = lay
  p.down = lay === 'side' ? down : null
  const file = p.trisFile, normal = downOf(p)
  p.tris = file && normal ? markRaw(layOn(file, normal)) : file
  p.size = sizeFor(p, normal)
  p.scale = p.fit = fitScale(p.size, session.printer?.bed)
}

function newPart(name: string, up: api.UploadedModel, tris: Float32Array | null, from: string, order = 0): Part {
  const p: Part = reactive({
    from, order,
    key: nextKey++, name, model: up.model, trisFile: tris ? markRaw(tris) : null, tris: null,
    sizeFile: up.size ?? (tris ? sizeOf(tris) : null), size: null, lying: up.lying ?? null,
    lay: 'file', layAuto: true, down: null, brim: 'auto', scale: 1, fit: 1, copies: Math.max(1, up.copies ?? 1), fill: null,
  }) as Part
  applyLay(p, p.lying?.flat_better ? 'flat' : 'file')
  return p
}

/** A file read here (for its picture) and uploaded once (for every slice after). A 3MF is read by the slicer
 *  as the parts in it; each comes back as an STL to draw. */
async function readParts(file: File): Promise<Part[]> {
  const up = await api.uploadModel(file)
  if ('models' in up) {
    return Promise.all(up.models.map(async (m, i) => {
      const stl = await api.modelFile(m.model, m.name)
      return newPart(m.name, m, parseModel(m.name, await stl.arrayBuffer()), file.name, i)
    }))
  }
  return [newPart(file.name, up, parseModel(file.name, await file.arrayBuffer()), file.name)]
}

/** How a plate is set up before its first slice, when it isn't new: a skipped part printed again
 *  (design/skip-objects/), the way it was. One entry per file, in order. */
export interface Setup {
  purpose?: Purpose
  settings?: Record<string, string>          // this print's own changes, as the plate had them
  supports?: string                          // a kind; auto (an older plate) is the usual'
  spool?: Choice
  parts?: { copies: number; scale?: number; lay?: Lay; down?: number[] | null; brim?: api.BrimAsk }[]
}

/** Models were picked: find the printer and spool, read and upload them, slice the plate four ways. */
let last: Parameters<typeof begin> | null = null
/** Try again, with the same files: after the slicer elsewhere was off (design/slicing-elsewhere/, A). */
export const retry = () => (last ? begin(...last) : Promise.resolve())

export async function begin(files: File[], spools: SpoolLike[], printerName: string | null | undefined, setup?: Setup): Promise<void> {
  last = [files, spools, printerName, setup]
  const gen = ++generation
  window.clearTimeout(timer)
  window.clearTimeout(soon)
  dropUnfinished()
  Object.assign(session, {
    stage: 'reading', error: '', errorInfo: null, parts: [], files: files.map(f => f.name), adding: 0, purpose: 'everyday', spool: null, spoolAuto: true,
    jobs: {}, jobFor: '', kinds: {}, kindsFor: '', lines: {}, placed: null, sent: null, sentLater: [], settings: {}, pending: false,
    left: [], picking: null, undo: null,
  })
  try {
    const options = session.options?.slicer ? session.options : await api.getOptions()   // fresh when it says who slices
    if (gen !== generation) return
    session.options = options
    const printer = matchPrinter(options.printers, printerName)
    if (!printer) throw new Error(`${printerName ?? 'This printer'} isn't set up for slicing yet.`)
    session.printer = printer
    const usual = await loadUsual(printer.supports ?? 'normal')
    if (gen !== generation) return
    session.usual = usual.supports
    session.kept = usual.kept ?? {}
    session.supports = session.usual
    session.spool = spoolChoice(pickSpool(spools, printer.materials), printer.materials)
    const parts = (await Promise.all(files.map(readParts))).flat()
    if (gen !== generation) return
    if (setup) {
      if (setup.purpose) session.purpose = setup.purpose
      if (setup.supports) session.supports = asKind(setup.supports, session.usual)
      if (setup.settings) session.settings = { ...setup.settings }
      if (setup.spool) { session.spool = setup.spool; session.spoolAuto = false }
      setup.parts?.forEach((s, i) => {
        const p = parts[i]
        if (!p) return
        if (s.lay && s.lay !== p.lay) { p.layAuto = false; applyLay(p, s.lay, s.down ?? null) }
        if (s.scale) p.scale = s.scale
        if (s.brim) p.brim = s.brim
        p.copies = Math.max(1, s.copies)
      })
    }
    session.parts = parts
    session.stage = 'ready'
    // a file of several parts: choose which to print before anything is sliced (a plate printed again is as it was)
    const several = setup ? null : severalFrom(parts)
    if (several) { session.picking = { from: several, first: true }; return }
    await sliceAll()
  } catch (e) {
    if (gen !== generation) return
    session.stage = 'error'
    session.error = e instanceof Error ? e.message : String(e)
    session.errorInfo = e instanceof api.SliceError ? e.info : null
  }
}

/** "Add a model": more parts on the same plate. */
export async function addFiles(files: File[]): Promise<void> {
  if (!files.length || session.stage !== 'ready') return
  const gen = generation
  session.adding += files.length
  try {
    const parts = (await Promise.all(files.map(readParts))).flat()
    if (gen !== generation) return
    session.parts.push(...parts)
    session.files.push(...files.map(f => f.name))
    session.sent = null
    const several = severalFrom(parts)
    if (several) { session.picking = { from: several, first: false }; return }
    await sliceAll()
  } finally {
    if (gen === generation) session.adding = Math.max(0, session.adding - files.length)
  }
}

function partRequest(p: Part): api.PartRequest {
  return { model: p.model!, copies: p.copies, scale: p.scale, lay: p.lay, ...(p.lay === 'side' && p.down ? { down: p.down } : {}),
    ...(p.brim !== 'auto' ? { brim: p.brim } : {}) }
}

function request(purpose: Purpose, png: string | null, parts: Part[], supports: SupportKind = session.supports): api.SliceRequest {
  const sp = session.spool!
  return {
    parts: parts.map(partRequest),
    printer: session.printer!.id, purpose, supports,
    kept: session.kept[purpose] ?? {}, settings: session.settings,
    material: sp.material, color: sp.color, slot: sp.slot == null ? null : sp.slot + 1,
    thumbnail: png,
  }
}

const pictured = () => (plate.value.length ? thumbnail(plate.value, session.spool?.color ?? '#8A8D91') : null)
/** What the other kinds were sliced for: the plate, the purpose and the spool. */
const kindsKey = () => JSON.stringify([session.jobFor, session.purpose, session.spool, session.settings, session.kept[session.purpose]])

/** Slice every purpose again, the chosen one first. seed: a slice already done for the chosen purpose (a kind
 *  picked on the Supports sheet), kept instead of slicing it again, with the kinds still worth showing. */
export async function sliceAll(seed?: { job: api.SliceJob; kinds: Partial<Record<SupportKind, api.SliceJob>> }): Promise<void> {
  if (!session.parts.length || !session.printer || !session.spool || session.parts.some(p => !p.model)) return
  const gen = ++generation
  window.clearTimeout(timer)
  window.clearTimeout(soon)
  session.pending = false
  dropUnfinished()
  session.jobFor = plateKey()
  session.jobs = seed ? { [session.purpose]: seed.job } : {}
  session.kinds = seed?.kinds ?? {}
  session.kindsFor = seed ? kindsKey() : ''
  if (seed?.job.placed?.length) session.placed = { for: session.jobFor, at: seed.job.placed }
  session.sent = null
  session.sentLater = []
  const png = pictured()
  const order = [session.purpose, ...PURPOSES.filter(p => p !== session.purpose)].filter(p => !session.jobs[p])
  for (const purpose of order) {
    try {
      const job = await api.startSlice(request(purpose, png, session.parts))
      if (gen !== generation) { void api.cancelJob(job.id); return }
      session.jobs[purpose] = job
    } catch (e) {
      if (gen !== generation) return
      session.jobs[purpose] = { id: '', state: 'failed', changes: [], error: e instanceof Error ? e.message : String(e) }
    }
  }
  poll(gen)
}

/** A change that comes in taps (the count): slice once they stop, and stop the slicer meanwhile. */
function sliceSoon() {
  window.clearTimeout(soon)
  dropUnfinished()
  session.pending = true
  soon = window.setTimeout(() => void sliceAll(), 500)
}

function poll(gen: number) {
  const waiting = [...PURPOSES.map(p => session.jobs[p]), ...SUPPORT_KINDS.map(k => session.kinds[k])].filter(unfinished)
  if (!waiting.length || gen !== generation) return
  window.clearTimeout(timer)
  timer = window.setTimeout(async () => {
    await Promise.all(waiting.map(async j => {
      try {
        const fresh = await api.getJob(j.id)
        if (gen !== generation) return
        const p = PURPOSES.find(k => session.jobs[k]?.id === fresh.id)
        if (p) {
          session.jobs[p] = fresh
          if (p === session.purpose && fresh.state === 'done' && fresh.placed?.length) session.placed = { for: session.jobFor, at: fresh.placed }
        }
        const k = SUPPORT_KINDS.find(x => session.kinds[x]?.id === fresh.id)
        if (k) session.kinds[k] = fresh
      } catch { /* the next round asks again */ }
    }))
    poll(gen)
  }, 600)
}

export function setPurpose(p: Purpose) {
  if (p === session.purpose) return
  session.purpose = p
  const done = session.jobs[p]
  if (done?.state === 'done' && done.placed?.length) session.placed = { for: session.jobFor, at: done.placed }
}
export function setSpool(c: Choice) { session.spool = c; session.spoolAuto = false; void sliceAll() }

/** The printer's spools arrived (or changed) after the model was picked: while the spool is still the
 *  app's own guess, take the one in the head. A spool the person chose is never replaced. */
export function followSpools(spools: SpoolLike[]) {
  if (!session.spoolAuto || !session.printer || session.stage !== 'ready') return
  const s = pickSpool(spools, session.printer.materials)
  if (!s) return
  const next = spoolChoice(s, session.printer.materials)
  const cur = session.spool
  if (cur && cur.slot === next.slot && cur.material === next.material && cur.color === next.color) return
  session.spool = next
  void sliceAll()
}

/** A kind picked on the Supports sheet. Its slice for the chosen purpose is kept when it's done; the one it
 *  replaces stays on the sheet. The other purposes are sliced again with it. */
export function setSupports(k: SupportKind) {
  if (k === session.supports) return
  const was = session.supports, cur = current.value
  const ready = session.kindsFor === kindsKey() ? session.kinds[k] : undefined
  session.supports = k
  if (ready?.state !== 'done') { void sliceAll(); return }
  const kinds: Partial<Record<SupportKind, api.SliceJob>> = {}
  for (const x of SUPPORT_KINDS) if (x !== k && session.kinds[x]?.state === 'done') kinds[x] = session.kinds[x]
  if (cur?.state === 'done') kinds[was] = cur
  void sliceAll({ job: ready, kinds })
}

/** The Supports sheet opened: slice the kinds not already sliced for this plate, purpose and spool. */
export async function askKinds(): Promise<void> {
  if (session.stage !== 'ready' || !session.printer || !session.spool || session.parts.some(p => !p.model)) return
  const key = kindsKey()
  if (session.kindsFor !== key) {
    for (const j of Object.values(session.kinds)) if (unfinished(j)) void api.cancelJob(j.id)
    session.kinds = {}
    session.kindsFor = key
  }
  const gen = generation
  const png = pictured()
  for (const k of SUPPORT_KINDS) {
    if (k === session.supports || session.kinds[k]) continue
    try {
      const job = await api.startSlice(request(session.purpose, png, session.parts, k))
      if (gen !== generation || session.kindsFor !== key) { void api.cancelJob(job.id); return }
      session.kinds[k] = job
    } catch (e) {
      if (gen !== generation) return
      session.kinds[k] = { id: '', state: 'failed', changes: [], error: e instanceof Error ? e.message : String(e) }
    }
  }
  poll(gen)
}

/** The slice for a kind on the sheet: the chosen one is the current slice. */
export function kindJob(k: SupportKind): api.SliceJob | null {
  if (k === session.supports) return current.value
  return session.kindsFor === kindsKey() ? session.kinds[k] ?? null : null
}

/** A slice's supports, fetched once it's done (a slice that needed none has none to fetch). */
export async function loadLines(j: api.SliceJob | null | undefined): Promise<void> {
  if (!j?.id || j.state !== 'done' || !j.supports_added || j.id in session.lines) return
  session.lines[j.id] = null
  try {
    session.lines[j.id] = markRaw(await api.getSupportLines(j.id))
  } catch {
    delete session.lines[j.id]               // asked again next time
  }
}

/** The plate as a slice placed it, for that slice's picture. */
export function plateOf(j: api.SliceJob | null | undefined): Float32Array {
  if (!j?.placed?.length) return plate.value
  return markRaw(compose(session.parts.map(p => ({ tris: p.tris, copies: p.copies, scale: p.scale })), j.placed))
}

/** How many of part i: sliced once the taps stop. */
export function setCopies(i: number, n: number) {
  const p = session.parts[i]
  if (!p) return
  const k = Math.max(1, Math.min(200, Math.round(n)))
  if (k === p.copies) return
  p.copies = k
  sliceSoon()
}
export function setScale(i: number, k: number) {
  const p = session.parts[i]
  if (!p || p.scale === k) return
  p.scale = k
  void sliceAll()
}
/** Which side down, chosen by the person: a side's normal, or null for the file's own bottom. Its own
 *  size and fit come with it. */
export function setSide(i: number, normal: number[] | null) {
  const p = session.parts[i]
  if (!p) return
  const cur = downOf(p)
  if ((cur == null && normal == null) || (cur && normal && same(cur, normal))) return
  p.layAuto = false
  if (normal == null) applyLay(p, 'file')
  else if (p.lying && same(normal, p.lying.flat_normal)) applyLay(p, 'flat')
  else applyLay(p, 'side', normal)
  void sliceAll()
}
/** A brim for part i and every copy of it (design/brim/, A); auto hands it back to the rule. */
export function setBrim(i: number, k: api.BrimAsk) {
  const p = session.parts[i]
  if (!p || p.brim === k) return
  p.brim = k
  void sliceAll()
}
/** Take part i off the plate. A part from a file of several waits beside the plate for "Change"; any part can
 *  come back with Undo. Sliced once the taps stop. */
export function removePart(i: number) {
  if (session.parts.length < 2 || !session.parts[i]) return
  const [p] = session.parts.splice(i, 1)
  if ([...session.parts, ...session.left].some(o => o.from === p.from)) session.left.push(p)
  session.undo = { part: p, at: i }
  sliceSoon()
}

export function undoRemove() {
  const u = session.undo
  if (!u) return
  session.left = session.left.filter(p => p.key !== u.part.key)
  session.parts.splice(Math.min(u.at, session.parts.length), 0, u.part)
  session.undo = null
  sliceSoon()
}

/** "Change": the picker again, for one file's parts. */
export function openPicker(from: string) { session.picking = { from, first: false }; session.undo = null }

/** The picker's answer: these of the file's parts on the plate, the rest beside it. */
export function pick(from: string, keep: Set<number>) {
  if (![...session.parts, ...session.left].some(p => p.from === from && keep.has(p.key))) return
  const r = pickFrom(session.parts, session.left, from, keep)
  session.parts = r.parts
  session.left = r.left
  session.picking = null
  session.undo = null
  if (session.jobFor !== plateKey()) void sliceAll()
}

/** The picker closed without an answer (only after the first time): whatever is on the plate gets sliced. */
export function closePicker() {
  session.picking = null
  if (session.jobFor !== plateKey()) void sliceAll()
}

/** "Make it 25": only what fits on the first plate. A part that went wholly to the next plate goes. */
export function onlyWhatFits() {
  const counts = current.value?.plates?.[0]?.counts
  if (!counts || counts.length !== session.parts.length) return
  const keep = session.parts.filter((p, i) => counts[i] > 0)
  keep.forEach(p => { p.copies = counts[session.parts.indexOf(p)] })
  session.parts = keep
  void sliceAll()
}

/** How many of part i fit on one plate with the others as they are ("Fill the plate"). Asked once per plate. */
export async function askFill(i: number): Promise<void> {
  const p = session.parts[i]
  if (!p?.model || !session.printer) return
  const key = plateKey(session.parts, i)
  if (p.fill?.for === key) return
  try {
    const a = await api.fitPart({ printer: session.printer.id, part: i,
      parts: session.parts.map(partRequest) })
    if (session.parts[i] === p) p.fill = { ...a, for: key }
  } catch { /* no number on the chip */ }
}

/** Put the chosen slice on the printer, and any later plates with it. Answers the first file's name there. */
export async function send(): Promise<string> {
  const job = current.value
  if (!job || job.state !== 'done') throw new Error('It isn\'t ready yet.')
  const r = await api.sendJob(job.id)
  session.sent = r.sent
  session.sentLater = r.later ?? []
  return r.sent
}

export function reset() {
  generation++
  window.clearTimeout(timer)
  window.clearTimeout(soon)
  dropUnfinished()
  Object.assign(session, {
    stage: 'idle', error: '', parts: [], files: [], adding: 0, jobs: {}, jobFor: '', kinds: {}, kindsFor: '', lines: {}, placed: null,
    left: [], picking: null, undo: null, pending: false,
    sent: null, sentLater: [], spool: null,
  })
}
