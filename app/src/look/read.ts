// Any model file, read on the device into parts to draw (design/look/). Nothing is uploaded.

import { parseModel, sizeOf } from '../slice/stl.ts'
import { modelName } from '../slice/plan.ts'
import { provisional } from '../slice/plate.ts'
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

/** What the file holds, said once: "13 parts" or the one part's name. Several files: "3 models". */
export function title(name: string, parts: Part[], files = 1): string {
  if (files > 1) return `${files} models`
  return parts.length === 1 ? parts[0].name || modelName(name) : `${parts.length} parts`
}

/** Several files on one plate: each file's parts stay where that file puts them, the files side by side in rows,
 *  the way a printer's plate stands them before Orca arranges it. */
export function sideBySide(files: Part[][], gap = 6): Part[] {
  if (files.length === 1) return files[0]
  const whole = files.map(together)
  const placed = provisional(whole.map((tris) => ({ tris, copies: 1, scale: 1 })), null, gap)
  return files.flatMap((parts, i) => {
    const [x0, x1, y0, y1, z0] = box(whole[i])
    const at = placed.find((p) => p.part === i)!
    const dx = at.x - (x0 + x1) / 2, dy = at.y - (y0 + y1) / 2
    return parts.map((p) => {
      const t = new Float32Array(p.tris.length)
      for (let j = 0; j < t.length; j += 3) { t[j] = p.tris[j] + dx; t[j + 1] = p.tris[j + 1] + dy; t[j + 2] = p.tris[j + 2] - z0 }
      return { name: p.name, tris: t }
    })
  })
}

function box(t: Float32Array): [number, number, number, number, number] {
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity, z0 = Infinity
  for (let i = 0; i < t.length; i += 3) {
    x0 = Math.min(x0, t[i]); x1 = Math.max(x1, t[i])
    y0 = Math.min(y0, t[i + 1]); y1 = Math.max(y1, t[i + 1])
    z0 = Math.min(z0, t[i + 2])
  }
  return [x0, x1, y0, y1, z0]
}
