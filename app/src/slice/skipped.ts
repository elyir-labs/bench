// Which parts of a plate were skipped mid-print (design/skip-objects/). Pure, so tests/slice.test.ts can pin it.

import type { IntentParts } from '../intent/types.ts'

/** How many copies of each part of the plate were skipped: by part index, from Elyir Bench's object names. */
export function skippedByPart(parts: IntentParts): Map<number, number> {
  const out = new Map<number, number>()
  for (const it of parts.items) {
    const m = /^p(\d+)c\d+__/.exec(it.name)
    if (it.state === 'skipped' && m) out.set(+m[1], (out.get(+m[1]) ?? 0) + 1)
  }
  return out
}

/** How many copies of each part a plate had, by part index, from Elyir Bench's object names (Print the rest). */
export function copiesByPart(objects: string[]): Map<number, number> {
  const out = new Map<number, number>()
  for (const name of objects) {
    const m = /^p(\d+)c\d+__/.exec(name)
    if (m) out.set(+m[1], (out.get(+m[1]) ?? 0) + 1)
  }
  return out
}

/** Whether "print it again" can be offered: something skipped, and named by Elyir Bench's slicer. */
export const canPrintAgain = (parts: IntentParts | null | undefined) => !!parts && skippedByPart(parts).size > 0
