// How would it print? (design/look/, A): one model, sliced by each paired printer's own slicer as Ready
// would start it, and nothing sent. Pure, so tests/look.test.ts can pin what each row says.

import type { PartRequest, PrinterOption, SliceJob, SliceRequest, UploadedModel, UploadedSet } from '../slice/api.ts'
import type { SlicerState } from '../slice/elsewhere.ts'
import { fitScale, pickSpool, spoolChoice, type Choice, type Purpose, type SpoolLike } from '../slice/plan.ts'
import { humanDuration } from '../intent/jobs.ts'

export const modelsOf = (up: UploadedModel | UploadedSet): UploadedModel[] => ('models' in up ? up.models : [up])

/** The plate Ready starts with: each part laid flat when that's better, shrunk to fit the bed if it must. */
export function plateFor(models: UploadedModel[], bed: number[] | null): { parts: PartRequest[]; shrunk: number | null } {
  let least = 1
  const parts = models.map((m): PartRequest => {
    const flat = !!m.lying?.flat_better
    const scale = fitScale(flat ? (m.lying?.size_flat ?? m.size) : m.size, bed)
    least = Math.min(least, scale)
    return { model: m.model, copies: Math.max(1, m.copies ?? 1), scale, lay: flat ? 'flat' : 'file' }
  })
  return { parts, shrunk: least < 1 ? least : null }
}

export function requestFor(models: UploadedModel[], printer: PrinterOption, spools: SpoolLike[], purpose: Purpose):
  { req: SliceRequest; shrunk: number | null; spool: Choice } {
  const spool = spoolChoice(pickSpool(spools, printer.materials), printer.materials)
  const { parts, shrunk } = plateFor(models, printer.bed)
  return {
    req: { parts, printer: printer.id, purpose, supports: printer.supports ?? 'normal',
      material: spool.material, color: spool.color, slot: spool.slot == null ? null : spool.slot + 1 },
    shrunk, spool,
  }
}

export type Row =
  | { kind: 'queued' | 'away' | 'offline' | 'none' }
  | { kind: 'slicer'; state: Exclude<SlicerState, { state: 'none' | 'ready' }> }
  | { kind: 'slicing'; job?: SliceJob }
  | { kind: 'done'; job: SliceJob; shrunk: number | null; spool: Choice
      /** on a Bench Box: the box's own words for the row ("Free now: Black PLA in slot 3"), and whether it can take it
       *  as things are (a printer with another filament loaded still has a time, grayed) */
      line?: string; fits?: boolean }
  | { kind: 'failed'; error: string }

/** time: the big words on the right; grams under them; note: the line under the printer's name. */
export function rowWords(r: Row): { time: string; grams: string; note: string } {
  const none = { time: '', grams: '' }
  switch (r.kind) {
    case 'queued': return { ...none, note: 'Waiting its turn' }
    case 'away': return { ...none, note: "Times come when you're home" }
    case 'offline': return { ...none, note: "Off, or can't be reached" }
    case 'none': return { ...none, note: "Doesn't slice" }
    case 'slicer': {
      const s = r.state
      if (s.state === 'waiting') return { ...none, note: `Waiting for ${s.name} to say yes` }
      if (s.state === 'refused') return { ...none, note: `${s.name} said no to slicing for it` }
      return { ...none, note: `${s.name ?? 'Its slicer'} is off` }
    }
    case 'slicing': {
      const j = r.job
      return { ...none, note: j?.state === 'queued' && j.behind ? `After ${j.behind}'s slice` : 'Slicing…' }
    }
    case 'failed': return { ...none, note: r.error }
    case 'done': {
      const e = r.job.estimate, plates = r.job.plates?.length ?? 1
      const bits = [r.shrunk ? `Shrunk to ${Math.round(r.shrunk * 100)}% to fit` : '', plates > 1 ? `${plates} plates` : '', r.line ?? r.spool.name]
      return { time: humanDuration(e?.seconds), grams: e?.grams != null ? `${Math.round(e.grams)} g` : '', note: bits.filter(Boolean).join(' · ') }
    }
  }
}

/** The printer to offer first: the first sliced one that can take it as things are and fits as it is, else the first
 *  that can take it, else the first sliced at all. */
export function firstPick(order: string[], rows: Record<string, Row>): string | null {
  const done = order.map((id) => [id, rows[id]] as const).filter((x): x is [string, Extract<Row, { kind: 'done' }>] => x[1]?.kind === 'done')
  const can = done.filter(([, r]) => r.fits !== false)
  return (can.find(([, r]) => !r.shrunk) ?? can[0] ?? done[0])?.[0] ?? null
}

/** The printers a phone is paired with directly that are also on a Bench Box it's paired with: asked through the box,
 *  so each is sliced once (names, as both say them). */
export function onABench(direct: { id: string; name: string }[], bench: { name: string }[]): Set<string> {
  const names = new Set(bench.map((b) => b.name.trim().toLowerCase()))
  return new Set(direct.filter((p) => names.has(p.name.trim().toLowerCase())).map((p) => p.id))
}
