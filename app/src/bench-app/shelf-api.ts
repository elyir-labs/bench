// The Bench Box's shelf, as its service answers (bench/shelf.py): the models it keeps, and each set up on the box's
// own slicer for the printer it goes to.

import type { SliceJob, SliceOptions } from '@/slice/api'
import type { SupportKind } from '@/slice/plan'
import { parseModel } from '@/slice/stl'
import { thumbnail } from '@/slice/render'
import { pathsFrom, stackFrom } from '@/look/layers'
import type { MyFilament, Printable, QueueItem } from './shelf'
import type { How, HowChange } from './how'
import type { SidePick, SidesView } from './sides'
import type { Cant, PlanPick, Plan, PlanBed } from './several'

export interface ShelfItem {
  id: string
  name: string
  file: string
  added: number
  prints: number
  parts: number
  picture: string | null
  last: { printer: string; printer_name: string; copies: number; material: string | null; color: string | null; at: number; how?: How;
          filament?: string | null; filament_name?: string | null } | null
  /** printed from a printer's own Print, and gathered by the box (design/bench-shelf/, A) */
  from: { printer: string; printer_name: string; file: string; at: number } | null
  /** how it prints, kept with it (design/bench-how/, A; docs/bench-how.md): the box fills in defaults */
  how?: How
}

async function answer<T>(r: Response): Promise<T> {
  const body = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(body.error || `The box said ${r.status}.`)
  return body as T
}
const json = (method: string, body?: unknown): RequestInit =>
  ({ method, headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) })

export const getShelf = () => fetch('/bench/shelf', { cache: 'no-store' }).then((r) => answer<ShelfItem[]>(r))
export const getPrintable = () => fetch('/bench/printable', { cache: 'no-store' }).then((r) => answer<Printable>(r))
export const removeModel = (id: string) => fetch(`/bench/shelf/${id}`, { method: 'DELETE' }).then((r) => answer<unknown>(r))
/** Set up on the box's slicer for one printer, with the model's how. `how` is laid over it for this slice only and not
 *  saved: the purpose sheet prices the other purposes so. */
export const startSetup = (id: string, req: { printer: string; copies: number; material: string; color: string | null; slot: number | null; how?: HowChange;
                                                filament?: string | null; filament_name?: string | null }) =>
  fetch(`/bench/shelf/${id}/slice`, json('POST', req)).then((r) => answer<SliceJob>(r))
/** Changes how the model prints, saved at once: settings merge, a setting set to null is removed. Returns the item. */
export const setHow = (id: string, change: HowChange) => fetch(`/bench/shelf/${id}/how`, json('PUT', change)).then((r) => answer<ShelfItem>(r))
/** Each part's sides, as the box's slicer measured them, and which is down (bench/shelf.py). */
export const getSides = (id: string) => fetch(`/bench/shelf/${id}/sides`, { cache: 'no-store' }).then((r) => answer<SidesView>(r))
/** Which side down for one part, kept with the model at once; returns every part's sides again. */
export const setSide = (id: string, pick: SidePick) => fetch(`/bench/shelf/${id}/side`, json('PUT', pick)).then((r) => answer<SidesView>(r))
/** The box slicer's options: the purposes' words, and the settings a person may change. */
export const getSliceOptions = () => fetch('/bench/slice-options', { cache: 'no-store' }).then((r) => answer<SliceOptions>(r))
/** A printer's own: its usual supports, and what it keeps for each purpose ("Yours", from its Print). */
export const getUsual = (printer: string) => fetch(`/bench/usual/${encodeURIComponent(printer)}`, { cache: 'no-store' })
  .then((r) => answer<{ supports: SupportKind; purposes: Record<string, Record<string, string>> }>(r))
export const getSetup = (job: string) => fetch(`/bench/slice/${job}`, { cache: 'no-store' }).then((r) => answer<SliceJob & { printer: string }>(r))
export const sendSetup = (job: string) => fetch(`/bench/slice/${job}/send`, json('POST', {})).then((r) => answer<{ sent: string; printing: boolean }>(r))
export const cancelSetup = (job: string) => fetch(`/bench/slice/${job}`, { method: 'DELETE' }).then(() => undefined, () => undefined)

/** A model onto the shelf, and its picture drawn here (a 3MF as the parts the slicer read in it). */
export async function addModel(file: File): Promise<ShelfItem> {
  const form = new FormData()
  form.append('model', file)
  const it = await fetch('/bench/shelf', { method: 'POST', body: form }).then((r) => answer<ShelfItem>(r))
  try {
    const tris = parseModel(file.name, await file.arrayBuffer()) ?? await modelTris(it)
    const png = tris ? thumbnail(tris, '#8A8D91') : null
    if (png) {
      const bytes = Uint8Array.from(atob(png), (c) => c.charCodeAt(0))
      return await fetch(`/bench/shelf/${it.id}/picture`, { method: 'PUT', body: bytes, headers: { 'Content-Type': 'image/png' } }).then((r) => answer<ShelfItem>(r))
    }
  } catch {
    // no picture (a STEP file, or one too big to draw): the shelf shows its name
  }
  return it
}

/** A shelf model's triangles to draw, as the slicer keeps its parts (a 3MF's each as an STL); null for one it can't
 *  read here (a STEP). */
export async function modelTris(it: Pick<ShelfItem, 'id' | 'parts' | 'file'>): Promise<Float32Array | null> {
  const each = (await partTris(it)).filter((t): t is Float32Array => !!t)
  return each.length ? concat(each) : null
}

/** Each part's triangles, in the parts' order (null for one it can't read here). */
export async function partTris(it: Pick<ShelfItem, 'id' | 'parts' | 'file'>): Promise<(Float32Array | null)[]> {
  const as = /\.3mf$/i.test(it.file) ? 'part.stl' : it.file
  const parts = await Promise.all(Array.from({ length: it.parts }, (_, n) =>
    fetch(`/bench/shelf/${it.id}/parts/${n}`).then((r) => (r.ok ? r.arrayBuffer() : null), () => null)))
  return parts.map((b) => (b ? parseModel(as, b) : null))
}

/** A setup's slice, to show it cut at a layer (design/bench-look/, C). */
export const getLayers = (job: string) => fetch(`/bench/slice/${job}/layers`, { cache: 'no-store' }).then((r) => answer<Parameters<typeof stackFrom>[0]>(r)).then(stackFrom)
export const getLayer = (job: string, n: number) =>
  fetch(`/bench/slice/${job}/layers/${n}`).then((r) => answer<Parameters<typeof pathsFrom>[1]>(r)).then((d) => pathsFrom(n, d))

function concat(all: Float32Array[]): Float32Array {
  const out = new Float32Array(all.reduce((n, a) => n + a.length, 0))
  let at = 0
  for (const a of all) { out.set(a, at); at += a.length }
  return out
}

// ── the queue (bench/bench_queue.py) ──

export const getQueue = () => fetch('/bench/queue', { cache: 'no-store' }).then((r) => answer<QueueItem[]>(r))
export const addToQueue = (req: { shelf: string; copies: number; material: string; color: string | null; filament?: string | null; filament_name?: string | null }) =>
  fetch('/bench/queue', json('POST', req)).then((r) => answer<QueueItem>(r))
export const reorderQueue = (ids: string[]) => fetch('/bench/queue', json('PUT', ids)).then((r) => answer<QueueItem[]>(r))
export const removeQueued = (id: string) => fetch(`/bench/queue/${id}`, { method: 'DELETE' }).then((r) => answer<unknown>(r))
// ── several at once (bench/plan.py; design/bench-several/, C) ──

/** The plan for the picked models. It answers at once; while `checking`, ask again with the same picks. */
export const getPlan = (picks: PlanPick[]) => fetch('/bench/plan', json('POST', { models: picks })).then((r) => answer<Plan>(r))
/** Print all (away: Add to the queue): each bed at the end of Up next, as the plan shows it. Nothing starts. */
export const printPlan = (beds: PlanBed[]) => fetch('/bench/plan/print', json('POST', { beds })).then((r) => answer<{ queued: QueueItem[]; cant: Cant[] }>(r))

/** Someone said the bed is clear: started, or the printer's own check said no (refused), or it isn't free any more. */
export async function startQueued(id: string, anyway = false, confirm = false):
  Promise<{ started?: string; printer?: string; refused?: { headline?: string; detail?: string; ask?: boolean } }> {
  const r = await fetch(`/bench/queue/${id}/start`, json('POST', { anyway, confirm }))
  const body = await r.json().catch(() => ({}))
  if (r.ok || body.refused) return body
  throw new Error(body.error || `The box said ${r.status}.`)
}

// ---- your filaments (bench/filaments.py; design/bench-material/, B) ------------------------------------------------

export interface LibraryFilament { preset: string; name: string; brand: string; material: string }

export async function getMine(): Promise<MyFilament[]> {
  const r = await fetch('/bench/filaments', { cache: 'no-store' })
  return r.ok ? ((await r.json()).mine as MyFilament[]) : []
}

export async function addMine(f: Omit<MyFilament, 'id'>): Promise<MyFilament> {
  const r = await fetch('/bench/filaments', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(f) })
  if (!r.ok) throw new Error(((await r.json().catch(() => ({}))) as { error?: string }).error ?? "The box didn't keep it.")
  return (await r.json()) as MyFilament
}

export async function removeMine(id: string): Promise<void> {
  await fetch(`/bench/filaments/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

export async function searchLibrary(q: string): Promise<{ filaments: LibraryFilament[]; total: number }> {
  const r = await fetch(`/bench/filaments/library?q=${encodeURIComponent(q)}`, { cache: 'no-store' })
  if (!r.ok) throw new Error("The box's slicer didn't answer.")
  return (await r.json()) as { filaments: LibraryFilament[]; total: number }
}
