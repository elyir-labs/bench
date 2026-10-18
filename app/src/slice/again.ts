// A part skipped mid-print, printed again (design/skip-objects/, A): the slicer remembered what each plate it
// sent was made of (elyir-bench/sliced in Moonraker); the skipped copies' names say which part they were
// (p0c7__...). Fetch those models back from the slicer and open Ready set up the way the plate was.

import type { IntentParts } from '@/intent/types'
import { skippedByPart } from './skipped'
import * as api from './api'
import { begin, useMoonraker, type Choice, type Setup } from './session'
export { canPrintAgain } from './skipped'
import type { Purpose, SpoolLike } from './plan'

interface Remembered {
  parts: { model: string; name: string; scale: number; lay: 'file' | 'flat' | 'side'; down?: number[]; brim?: api.BrimAsk }[]
  purpose: Purpose; supports: string; settings?: Record<string, string>; material: string; color: string | null; slot: number | null
}

type Call = <T = unknown>(method: string, params?: Record<string, unknown>) => Promise<T>

export async function printAgain(call: Call, filename: string, parts: IntentParts, spools: SpoolLike[], printerName: string): Promise<void> {
  useMoonraker(call)
  const r = await call<{ value?: Record<string, Remembered> }>('server.database.get_item', { namespace: 'elyir-bench', key: 'sliced' }).catch(() => null)
  const rec = r?.value?.[filename.split('/').pop() ?? filename]
  if (!rec) throw new Error("This plate wasn't sliced here, so there's nothing to print again from.")
  const want = [...skippedByPart(parts)].filter(([i]) => rec.parts[i])
  const files = await Promise.all(want.map(([i]) => api.modelFile(rec.parts[i].model, rec.parts[i].name)))
  const spool: Choice = { slot: rec.slot == null ? null : rec.slot - 1, material: rec.material, color: rec.color, name: rec.material }
  const live = spools.find(s => s.slot === spool.slot)
  if (live?.name) spool.name = live.name
  const setup: Setup = {
    purpose: rec.purpose, supports: rec.supports, settings: rec.settings, spool,
    parts: want.map(([i, n]) => ({ copies: n, scale: rec.parts[i].scale, lay: rec.parts[i].lay, down: rec.parts[i].down ?? null,
      brim: rec.parts[i].brim ?? 'auto' })),
  }
  void begin(files, spools, printerName, setup)
}
