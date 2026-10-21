// A part skipped mid-print, printed again (design/skip-objects/, A): the slicer remembered what each plate it
// sent was made of (elyir-bench/sliced in Moonraker); the skipped copies' names say which part they were
// (p0c7__...). Fetch those models back from the slicer and open Ready set up the way the plate was.
// The rest of a print the power took (design/power-loss/, A) comes the same way, each part cut where it stopped.

import type { IntentParts, LostView } from '@/intent/types'
import { copiesByPart, skippedByPart } from './skipped'
import * as api from './api'
import { begin, useMoonraker, type Choice, type Setup } from './session'
export { canPrintAgain } from './skipped'
import type { Purpose, SpoolLike } from './plan'

interface Remembered {
  parts: { model: string; name: string; scale: number; lay: 'file' | 'flat' | 'side'; down?: number[]; brim?: api.BrimAsk }[]
  purpose: Purpose; supports: string; settings?: Record<string, string>; material: string; color: string | null; slot: number | null
}

type Call = <T = unknown>(method: string, params?: Record<string, unknown>) => Promise<T>

async function remembered(call: Call, filename: string): Promise<Remembered | null> {
  useMoonraker(call)
  const r = await call<{ value?: Record<string, Remembered> }>('server.database.get_item', { namespace: 'elyir-bench', key: 'sliced' }).catch(() => null)
  return r?.value?.[filename.split('/').pop() ?? filename] ?? null
}

/** Whether Print the rest can be offered: the slicer here made that file, so its models are known. */
export const canPrintRest = async (call: Call, filename: string) => !!(await remembered(call, filename))

function spoolOf(rec: Remembered, spools: SpoolLike[]): Choice {
  const spool: Choice = { slot: rec.slot == null ? null : rec.slot - 1, material: rec.material, color: rec.color, name: rec.material }
  const live = spools.find(s => s.slot === spool.slot)
  if (live?.name) spool.name = live.name
  return spool
}

export async function printAgain(call: Call, filename: string, parts: IntentParts, spools: SpoolLike[], printerName: string): Promise<void> {
  const rec = await remembered(call, filename)
  if (!rec) throw new Error("This plate wasn't sliced here, so there's nothing to print again from.")
  const want = [...skippedByPart(parts)].filter(([i]) => rec.parts[i])
  const files = await Promise.all(want.map(([i]) => api.modelFile(rec.parts[i].model, rec.parts[i].name)))
  const setup: Setup = {
    purpose: rec.purpose, supports: rec.supports, settings: rec.settings, spool: spoolOf(rec, spools),
    parts: want.map(([i, n]) => ({ copies: n, scale: rec.parts[i].scale, lay: rec.parts[i].lay, down: rec.parts[i].down ?? null,
      brim: rec.parts[i].brim ?? 'auto' })),
  }
  void begin(files, spools, printerName, setup)
}

/** Each part cut at the height the print reached and set down on the plate (already laid and sized as printed),
 * as many of each as were still printing; parts that were done below that height are left off. */
export async function printRest(call: Call, lost: LostView, spools: SpoolLike[], printerName: string): Promise<void> {
  const rec = await remembered(call, lost.file)
  if (!rec || lost.z == null) throw new Error("This print wasn't sliced here, so there's no model to print the rest from.")
  const copies = copiesByPart(lost.objects)
  const cut = await Promise.all(rec.parts.map((p, i) => (copies.size && !copies.has(i) ? null
    : api.cutModel(p.model, { z: lost.z!, lay: p.lay, down: p.down ?? null, scale: p.scale }))))
  const want = cut.flatMap((c, i) => (c ? [[c, i] as const] : []))
  if (!want.length) throw new Error('Nothing of it is left above where it stopped.')
  const files = await Promise.all(want.map(([c]) => api.modelFile(c.model, c.name)))
  const setup: Setup = {
    purpose: rec.purpose, supports: rec.supports, settings: rec.settings, spool: spoolOf(rec, spools),
    parts: want.map(([, i]) => ({ copies: copies.get(i) ?? 1, scale: 1, lay: 'file', down: null, brim: rec.parts[i].brim ?? 'auto' })),
  }
  void begin(files, spools, printerName, setup)
}
