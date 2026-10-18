// Any model file, read on the device into parts to draw (design/look/). Nothing is uploaded.

import { parseModel, sizeOf } from '../slice/stl.ts'
import { modelName } from '../slice/plan.ts'
import { read3mf } from './threemf.ts'

export interface Part { name: string; tris: Float32Array }

export const MODEL_EXT = /\.(stl|obj|3mf|step|stp)$/i
export const isStep = (name: string) => /\.(step|stp)$/i.test(name)

export async function readModel(name: string, buf: ArrayBuffer, step: (buf: ArrayBuffer) => Promise<Part[]>): Promise<Part[]> {
  if (!MODEL_EXT.test(name)) throw new Error(`${name} isn't a model this can show: an STL, 3MF, STEP or OBJ file.`)
  let parts: Part[]
  if (/\.3mf$/i.test(name)) parts = await read3mf(buf)
  else if (isStep(name)) parts = await step(buf)
  else { const tris = parseModel(name, buf); parts = tris ? [{ name: modelName(name), tris }] : [] }
  parts = parts.filter((p) => p.tris.length >= 9)
  if (!parts.length) throw new Error(`There's no model in ${name}.`)
  return parts
}

/** Every part's triangles together, as placed in the file. */
export function together(parts: Part[]): Float32Array {
  if (parts.length === 1) return parts[0].tris
  const all = new Float32Array(parts.reduce((n, p) => n + p.tris.length, 0))
  let at = 0
  for (const p of parts) { all.set(p.tris, at); at += p.tris.length }
  return all
}

/** "135 × 51 × 10 mm", whole millimeters, a tenth below 10 mm. */
export function sizeWords(tris: Float32Array): string {
  const s = sizeOf(tris)
  return s ? s.map((d) => (d < 10 ? Math.round(d * 10) / 10 : Math.round(d))).join(' × ') + ' mm' : ''
}

/** What the file holds, said once: "13 parts" or the one part's name. */
export function title(name: string, parts: Part[]): string {
  return parts.length === 1 ? parts[0].name || modelName(name) : `${parts.length} parts`
}
