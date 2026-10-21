// The slicing service (slicer/slice_service.py, docs/slicer.md), reached at /slice on the same
// origin: Vite proxies it in dev, nginx in front of the printer will in production.

import { authHeaders } from '@/auth'
import type { Editable, SliceChange } from './plan'
import type { ColorsResult, FileColor, Purge } from './colors'
import { decodeLines } from './supports'
import { stateFrom, type SlicerInfo, type SlicerState } from './elsewhere'
import { BASE as ROOT } from '@/base'

export interface PurposeOption { id: string; label: string; summary: string }
export interface PrinterOption {
  id: string
  name: string
  materials: string[]
  slots: number
  bed: number[] | null
  base: string
  supports?: 'normal' | 'tree'   // the kind its process preset prints: where "your usual" starts
  unit?: boolean                 // it has a filament unit: colors come from slots (design/multi-color/)
  purges?: Purge[]               // what Between colors offers, its usual first
  change_seconds?: number        // one color change by the unit
}
export interface SliceOptions { purposes: PurposeOption[]; supports: string[]; printers: PrinterOption[]; models: string[]; editable?: Editable[]; slicer?: SlicerInfo }
/** A side the model can rest on: the side facing `normal` goes down. contact: what really touches the
 *  plate (mm²); size [w, d, h] lying so; support: area facing down over 45° above the plate (mm²). */
export interface Side { normal: number[]; contact: number; size: number[]; support: number }
/** How the model sits (design/orientation/, A): flat_better when its flattest side isn't down. */
export interface Lying {
  down_area: number
  flat_area: number
  flat_normal: number[]
  flat_better: boolean
  tilt: number
  size_flat: number[] | null
  sides?: Side[]
}
export interface UploadedModel { model: string; name: string; size: number[] | null; lying?: Lying | null; copies?: number }
/** A 3MF answers with the parts in it, each already its own model (with how many times it's placed). */
export interface UploadedSet { models: UploadedModel[]; from: string }
/** A 3MF that brings its own colors stays whole (design/multi-color/): its colors, and pieces to draw it with. */
export interface UploadedProject extends UploadedModel {
  colors: { colors: FileColor[]; painted: boolean; heights: { z: number; to: number }[] }
  pieces: { piece: number; name: string; filament: number }[]
}
/** One plate the slicer made (design/plate/): what didn't fit on the first goes on the next. */
export interface SlicedPlate { plate: number; seconds: number | null; time: string | null; grams: number | null; counts: number[]; gcode: string }
export interface FitAnswer { part: number; fits: number; others_fit: boolean; at_least: boolean }
/** The brim a part prints with (design/brim/, A): kind auto leaves it to Orca (a file not measured here).
 *  by: who decided; rule: what the rule picks, still known after someone picks another. */
export type BrimAsk = 'auto' | 'none' | 'ears' | 'all'
export interface BrimPick { kind: BrimAsk; why: string; by: 'auto' | 'you' | 'kept'; rule?: 'none' | 'ears' | 'all' }
export interface SlicedPart { model: string; copies: number; scale: number; lay: string; brim?: BrimAsk; brim_pick?: BrimPick; spool?: number }
export interface SliceJob {
  id: string
  state: 'queued' | 'slicing' | 'done' | 'failed' | 'cancelled'
  changes: SliceChange[]
  estimate?: { seconds: number | null; time: string | null; grams: number | null; layers: number | null; changes_seconds?: number }
  colors?: ColorsResult              // several colors: each spool's use and every change
  supports_added?: boolean
  gcode?: string
  plates?: SlicedPlate[]
  placed?: { part: number; x: number; y: number; turn: number }[]
  parts?: SlicedPart[]
  warnings?: string[]
  values?: Record<string, string>   // every editable setting as it prints (design/edit-settings/, C)
  before?: Record<string, string>   // the same before the person's own changes: what the purpose gives
  error?: string
  error_detail?: string
  ahead?: number                     // queued: slices before it, on a slicer shared by printers
  behind?: string | null             // the printer whose slice is going now
}
export interface PartRequest {
  model: string
  copies: number
  scale?: number
  lay?: 'file' | 'flat' | 'side'   // flat: onto its flattest side; side: onto `down`, a side the person picked
  down?: number[]
  brim?: BrimAsk                   // auto (left out): the rule picks; none | ears | all: the person did
  spool?: number                   // which of the plate's colors, when it has several
}
export interface SliceRequest {
  parts: PartRequest[]
  printer: string
  purpose: string
  supports: string
  material: string
  color?: string | null
  slot?: number | null      // 1-based, as people count
  thumbnail?: string | null // PNG, base64
  kept?: Record<string, string>      // the person's own for this purpose
  settings?: Record<string, string>  // the person's, for this print only
  spools?: { material: string; color: string | null; slot: number | null; hand: boolean }[]   // several colors, slot 1-based
  purge?: Purge
  one_after_other?: boolean
}

const BASE = `${ROOT}/slice`

/** The slicer's own words, and what came with them ({off, slicer} when the slicer is elsewhere and off). */
export class SliceError extends Error {
  constructor(message: string, public info: Record<string, any> = {}) { super(message) }
}

async function json<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const body = await r.json().catch(() => null)
    if (body?.error) throw new SliceError(body.error, body)
    // No answer of its own: the proxy in front (Vite, nginx) couldn't reach it.
    if (r.status >= 500) throw new Error("Couldn't reach the slicer. It may not be running.")
    throw new Error(`The slicer answered ${r.status}`)
  }
  return r.json()
}

const opts = (init: RequestInit = {}): RequestInit => ({ credentials: 'include', ...init, headers: authHeaders(init.headers as Record<string, string>) })

export const getOptions = () => fetch(`${BASE}/options`, opts()).then(r => json<SliceOptions>(r))

/** Whether this printer slices at all, on itself or on another machine (`slicer: on`, `auto`, or an address),
 *  and how that stands (design/slicing-elsewhere/, A). Without a slicer nginx has no /slice, so the app's own
 *  page answers with a 200. A slicer that's set up but down still counts: it answers words of its own. */
let here: Promise<SlicerState> | null = null
export function slicerStatus(fresh = false): Promise<SlicerState> {
  if (fresh || !here) {
    here = fetch(`${BASE}/options`, opts({ cache: 'no-store' }))
      .then(async r => stateFrom(r.status, r.headers.get('content-type') ?? '', await r.json().catch(() => null)),
            () => ({ state: 'down', name: null }) as SlicerState)
  }
  return here
}

export interface SlicerPrinter { id: string; name: string; joined: boolean }
/** On the slicer itself: who it slices for (its Care), and stopping one of them. */
export const slicerPrinters = () => fetch(`${BASE}/printers`, opts({ cache: 'no-store' })).then(r => json<{ slicer: string; printers: SlicerPrinter[] }>(r))
export const stopPrinter = (id: string) => fetch(`${BASE}/printers/${encodeURIComponent(id)}`, opts({ method: 'DELETE' })).then(r => json<unknown>(r))

export function uploadModel(file: File): Promise<UploadedModel | UploadedSet | UploadedProject> {
  const f = new FormData()
  f.append('model', file, file.name)
  return fetch(`${BASE}/models`, opts({ method: 'POST', body: f })).then(r => json<UploadedModel | UploadedSet | UploadedProject>(r))
}

/** One piece of a 3MF with colors, as an STL to draw. */
export async function modelPiece(id: string, k: number): Promise<ArrayBuffer> {
  const r = await fetch(`${BASE}/models/${id}/piece/${k}`, opts())
  if (!r.ok) throw new Error(`The slicer answered ${r.status}`)
  return r.arrayBuffer()
}

export const startSlice = (req: SliceRequest) =>
  fetch(BASE, opts({ method: 'POST', body: JSON.stringify(req), headers: { 'content-type': 'application/json' } })).then(r => json<SliceJob>(r))

export const getJob = (id: string) => fetch(`${BASE}/${id}`, opts({ cache: 'no-store' })).then(r => json<SliceJob>(r))

/** Not wanted any more (the spool, size or supports changed): the slicer drops or stops it. */
export const cancelJob = (id: string) => fetch(`${BASE}/${id}`, opts({ method: 'DELETE' })).then(() => undefined, () => undefined)

/** Every plate goes to the printer; the first is the one printed now. */
export const sendJob = (id: string) =>
  fetch(`${BASE}/${id}/send`, opts({ method: 'POST' })).then(r => json<{ sent: string; printing: boolean; later?: string[] }>(r))

/** A model as it was uploaded, to slice a skipped part again (design/skip-objects/). Kept a day. */
export async function modelFile(id: string, name: string): Promise<File> {
  const r = await fetch(`${BASE}/models/${id}/file`, opts())
  if (!r.ok) throw new Error(r.status === 404 ? "That model isn't on the slicer any more (it keeps them a day)." : `The slicer answered ${r.status}`)
  return new File([await r.blob()], name)
}

/** What's above z of a model as it was printed, as a model of its own (Print the rest, design/power-loss/).
 * null when nothing of it is above z. */
export async function cutModel(id: string, ask: { z: number; lay: string; down?: number[] | null; scale: number }): Promise<{ model: string; name: string } | null> {
  const r = await fetch(`${BASE}/models/${id}/cut`, opts({ method: 'POST', body: JSON.stringify(ask), headers: { 'content-type': 'application/json' } }))
  if (r.status === 422) return null
  if (r.status === 404) throw new Error("That model isn't on the slicer any more (it keeps them a day).")
  return json<{ model: string; name: string }>(r)
}

export const getSupportLines = (id: string) =>
  fetch(`${BASE}/${id}/supports`, opts()).then(r => json<{ count: number; width: number; segs: string }>(r)).then(decodeLines)

/** How many of one part fit on a plate with the others ("Fill the plate"). Orca arranges; nothing is sliced. */
export const fitPart = (req: { printer: string; parts: PartRequest[]; part: number }) =>
  fetch(`${BASE}/fit`, opts({ method: 'POST', body: JSON.stringify(req), headers: { 'content-type': 'application/json' } })).then(r => json<FitAnswer>(r))
