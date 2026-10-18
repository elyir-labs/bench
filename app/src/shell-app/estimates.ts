// How would it print? (design/look/, A): the model on the Look page, sliced for each printer, one after another (they
// often share one slicer). Nothing is sent: a slice asked for here is never printed, and it's dropped when the page
// asks again or closes.
// - A printer paired with this phone: at home, through its own /slice.
// - A Bench Box paired with this phone (design/bench-look/, C): once, through its public name, for every printer on its
//   bench, with the box's own rules for which filament and which printer (bench-app/shelf.ts), so the phone and the
//   box's screen say the same. The model goes to the box to look at, off its shelf unless it's kept.

import { reactive } from 'vue'
import { benches, printers, type LiveBench, type LivePrinter } from './printers'
import { statusOf } from './status'
import { stateFrom } from '@/slice/elsewhere'
import { matchPrinter, type Purpose, type SpoolLike } from '@/slice/plan'
import type { SliceJob, SliceOptions, UploadedModel, UploadedSet } from '@/slice/api'
import type { Intent } from '@/intent/types'
import { firstPick, modelsOf, onABench, requestFor, type Row } from '@/look/estimate.ts'
import { pathsFrom, stackFrom, type LayerPaths, type LayerStack } from '@/look/layers.ts'
import { choices, printOn, timeable, type MyFilament, type Printable } from '@/bench-app/shelf'

/** Who a row is: its name, and the Bench Box it's on (rows on a box are grouped under its name). */
export interface RowInfo { name: string; bench?: string; pid?: string }

export const est = reactive<{ purpose: Purpose; order: string[]; rows: Record<string, Row>; info: Record<string, RowInfo>
  slicer: string | null; picked: string | null; open: boolean; kept: string[] }>({
  purpose: 'everyday', order: [], rows: {}, info: {}, slicer: null, picked: null, open: false, kept: [],
})

interface Asker { base: string | null; token: string; name: string }

let gen = 0
let file: File | null = null
let uploads = new Map<string, UploadedModel[]>()     // per printer, for this file: a new purpose doesn't upload again
let looks = new Map<string, string>()                 // per Bench Box, the model it was sent to look at
let running: { who: Asker; path: string } | null = null

const headers = (who: Asker, extra: Record<string, string> = {}) => ({ ...extra, Authorization: `Bearer ${who.token}` })

async function call<T>(who: Asker, path: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(`${who.base}${path}`, { ...init, cache: 'no-store', headers: headers(who, init.headers as Record<string, string>) })
  const body = await r.json().catch(() => null)
  if (!r.ok) throw new Error(body?.error ?? body?.message ?? `${who.name} answered ${r.status}`)
  return body as T
}
const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body), headers: { 'content-type': 'application/json' } })

function drop() {
  const r = running
  running = null
  if (r) void fetch(`${r.who.base}${r.path}`, { method: 'DELETE', headers: headers(r.who) }).catch(() => undefined)
}

const benchOf = (id: string) => benches.find((b) => b.id === est.info[id]?.bench)

/** Where a done row's slice is read: the printer's own /slice, or its box's. */
function doneJob(id: string): { who: Asker; path: string } | null {
  const row = est.rows[id]
  if (row?.kind !== 'done' || !row.job.id) return null
  const b = benchOf(id)
  if (b) return b.base ? { who: b, path: `/bench/slice/${row.job.id}` } : null
  const p = printers.find((x) => x.id === id)
  return p?.base ? { who: p, path: `/slice/${row.job.id}` } : null
}

// Layers of a slice (design/look/, A with C's layers), kept while the page is open
const stacks = new Map<string, Promise<LayerStack>>()
const paths = new Map<string, Promise<LayerPaths>>()

export function layerStack(id: string): Promise<LayerStack> | null {
  const d = doneJob(id)
  if (!d) return null
  const key = `${id}${d.path}`
  if (!stacks.has(key)) {
    const got = call<Parameters<typeof stackFrom>[0]>(d.who, `${d.path}/layers`).then(stackFrom)
    got.catch(() => stacks.delete(key))
    stacks.set(key, got)
  }
  return stacks.get(key)!
}

export function layerPaths(id: string, n: number): Promise<LayerPaths> | null {
  const d = doneJob(id)
  if (!d) return null
  const key = `${id}${d.path}/${n}`
  if (!paths.has(key)) {
    if (paths.size > 60) paths.delete(paths.keys().next().value!)
    const got = call<Parameters<typeof pathsFrom>[1]>(d.who, `${d.path}/layers/${n}`).then((r) => pathsFrom(n, r))
    got.catch(() => paths.delete(key))
    paths.set(key, got)
  }
  return paths.get(key)!
}

/** Stop asking: the page closed, or another file came. */
export function stopEstimates() {
  gen++
  drop()
  stacks.clear()
  paths.clear()
  file = null
  uploads = new Map()
  looks = new Map()
  Object.assign(est, { order: [], rows: {}, info: {}, slicer: null, picked: null, open: false, kept: [] })
}

export function estimate(f: File, purpose: Purpose = est.purpose) {
  if (f !== file) { stopEstimates(); file = f }
  const g = ++gen
  drop()
  const boxes = benches.filter((b) => b.reach !== 'unpaired')
  const skip = onABench(printers, boxes.flatMap((b) => b.printers))
  const own = printers.filter((p) => p.reach !== 'unpaired' && !skip.has(p.id))
  const info: Record<string, RowInfo> = {}
  for (const b of boxes) for (const x of b.printers) info[`${b.id}/${x.id}`] = { name: x.name, bench: b.id, pid: x.id }
  for (const p of own) info[p.id] = { name: p.name }
  Object.assign(est, { purpose, open: true, picked: null, info, order: Object.keys(info) })
  est.rows = Object.fromEntries(Object.keys(info).map((id) => [id, info[id].bench ? { kind: 'queued' } : rowBefore(own.find((p) => p.id === id)!)]))
  void (async () => {
    for (const b of boxes) {
      if (g !== gen) return
      await fromBench(b, f, purpose, g)
    }
    for (const p of own) {
      if (g !== gen) return
      if (p.reach !== 'home' || !p.base) { est.rows[p.id] = rowBefore(p, true); continue }
      est.rows[p.id] = { kind: 'slicing' }
      const row = await one(p, f, purpose, g).catch((e): Row => ({ kind: 'failed', error: (e as Error).message }))
      if (g !== gen) return
      est.rows[p.id] = row
      est.picked ??= firstPick(est.order, est.rows)
    }
  })()
}

function rowBefore(p: LivePrinter, final = false): Row {
  if (p.reach === 'home') return { kind: 'queued' }
  if (p.reach === 'away') return { kind: 'away' }
  return p.reach === 'checking' && !final ? { kind: 'queued' } : { kind: 'offline' }
}

async function one(p: LivePrinter, f: File, purpose: Purpose, g: number): Promise<Row> {
  const r = await fetch(`${p.base}/slice/options`, { cache: 'no-store', headers: headers(p) })
  const body = await r.json().catch(() => null)
  const st = stateFrom(r.status, r.headers.get('content-type') ?? '', body)
  if (st.state === 'none') return { kind: 'none' }
  if (st.state !== 'ready') return { kind: 'slicer', state: st }
  const options = body as SliceOptions
  const printer = matchPrinter(options.printers, p.name) ?? options.printers[0]
  if (!printer) return { kind: 'none' }
  est.slicer ??= st.slicer?.name ?? null
  let models = uploads.get(p.id)
  if (!models) {
    const form = new FormData()
    form.append('model', f, f.name)
    models = modelsOf(await call<UploadedModel | UploadedSet>(p, '/slice/models', { method: 'POST', body: form }))
    uploads.set(p.id, models)
  }
  if (g !== gen) return { kind: 'queued' }
  const { req, shrunk, spool } = requestFor(models, printer, (p.intent?.spools ?? []) as SpoolLike[], purpose)
  const job = await follow(p, '/slice', await call<SliceJob>(p, '/slice', json('POST', req)), p.id, g)
  if (!job) return { kind: 'queued' }
  if (job.state !== 'done') return { kind: 'failed', error: job.error ?? "It couldn't be sliced." }
  return { kind: 'done', job, shrunk, spool }
}

/** A job asked for, polled until it's done (null: the page asked for something else meanwhile). */
async function follow(who: Asker, at: string, job: SliceJob, id: string, g: number): Promise<SliceJob | null> {
  running = { who, path: `${at}/${job.id}` }
  while (job.state === 'queued' || job.state === 'slicing') {
    if (g !== gen) return null
    est.rows[id] = { kind: 'slicing', job }
    await new Promise((res) => setTimeout(res, 1000))
    job = await call<SliceJob>(who, `${at}/${job.id}`)
  }
  running = null
  return g === gen ? job : null
}

/** Every printer on a Bench Box, as its own model page would set it up: the same filament and the same rows. */
async function fromBench(b: LiveBench, f: File, purpose: Purpose, g: number): Promise<void> {
  const ids = b.printers.map((x) => `${b.id}/${x.id}`)
  const fail = (error: string) => { for (const id of ids) if (est.rows[id]?.kind !== 'done') est.rows[id] = { kind: 'failed', error } }
  if (!b.base) return fail("Can't reach the Bench Box")
  try {
    const [intents, printable, mine] = await Promise.all([
      call<Record<string, Intent | null>>(b, '/bench/intents'), call<Printable>(b, '/bench/printable'),
      call<{ mine: MyFilament[] }>(b, '/bench/filaments').then((x) => x.mine, () => [] as MyFilament[])])
    const bps = b.printers.map((x) => ({ id: x.id, name: x.name, live: !!intents[x.id], intent: intents[x.id] ?? null }))
    const fil = choices(bps, printable, mine)[0] ?? null
    const rows = printOn(bps, fil, printable)
    const can = new Set(timeable(rows, printable, fil))
    est.slicer ??= b.name
    let item = looks.get(b.id)
    if (!item) {
      const form = new FormData()
      form.append('model', f, f.name)
      item = (await call<{ id: string }>(b, '/bench/look', { method: 'POST', body: form })).id
      looks.set(b.id, item)
    }
    for (const r of rows) {
      const id = `${b.id}/${r.id}`
      if (g !== gen || !fil) return
      if (!can.has(r.id)) { est.rows[id] = { kind: 'failed', error: r.line }; continue }
      est.rows[id] = { kind: 'slicing' }
      const named = fil.preset ? { filament: fil.preset, filament_name: fil.name } : {}
      const asked = await call<SliceJob>(b, `/bench/shelf/${item}/slice`, json('POST',
        { printer: r.id, copies: 1, material: fil.material, color: fil.color, slot: r.slot, how: { purpose }, ...named }))
      const job = await follow(b, '/bench/slice', asked, id, g)
      if (!job) return
      est.rows[id] = job.state === 'done'
        ? { kind: 'done', job, shrunk: null, spool: { slot: r.slot == null ? null : r.slot - 1, material: fil.material, color: fil.color, name: fil.name }, line: r.line, fits: r.fits }
        : { kind: 'failed', error: job.error ?? "It couldn't be set up." }
      est.picked ??= firstPick(est.order, est.rows)
    }
    if (!fil) fail('Nothing is loaded on the bench')
  } catch (e) {
    if (g === gen) fail((e as Error).message)
  }
}

/** Keep it on the Bench Box's shelf: the model sent to look at becomes one of the shelf's. */
export async function keepOnBench(benchId: string): Promise<boolean> {
  const b = benches.find((x) => x.id === benchId), item = looks.get(benchId)
  if (!b?.base || !item) return false
  await call(b, `/bench/shelf/${item}/keep`, { method: 'PUT' })
  if (!est.kept.includes(benchId)) est.kept = [...est.kept, benchId]
  return true
}

/** "Open on the Bench Box…": kept on its shelf, and its own page for that printer (it sets it up and asks about the bed). */
export async function openOnBench(id: string): Promise<void> {
  const i = est.info[id], b = benchOf(id), item = i?.bench ? looks.get(i.bench) : null
  if (!i?.bench || !b?.base || !item) return
  const tab = window.open('', '_blank')
  await keepOnBench(i.bench).catch(() => false)
  const url = `${b.base}/print/${item}?on=${encodeURIComponent(i.pid ?? '')}`
  if (tab) tab.location.href = url
  else window.location.href = url
}

/** The line under a row's name: the box's own words for its printers, else what it says plus the printer's state. */
export function lineFor(id: string, note: string): string {
  if (est.info[id]?.bench) return note
  const p = printers.find((x) => x.id === id)
  return [note, p && est.rows[id]?.kind === 'done' ? statusOf(p).word : ''].filter(Boolean).join(' · ')
}
