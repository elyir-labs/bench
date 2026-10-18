// Which side down for a model on the Bench Box's shelf (the printer's own design/orientation/, on the box 11 October 2026):
// each part's sides as the box's slicer measured them (GET /bench/shelf/{id}/sides, bench/shelf.py), the one picked kept
// with the model, else the part's own: laid flat for you, as in the file, or as a printer's plate had it. Pure, so
// tests/bench-sides.test.ts can pin the words; ModelPage and the plan's move sheet draw them (SideSheet).

import type { Lying } from '../slice/api.ts'
import { compose, provisional } from '../slice/plate.ts'
import { sameSide, sideLine, sideOptions, type SideOption } from '../slice/sides.ts'
import { layOn } from '../slice/stl.ts'

export type Lay = 'file' | 'flat' | 'side'
export interface SidePart {
  n: number
  name: string
  lying: Lying | null
  lay: Lay
  down?: number[]
  normal: number[] | null       // the side down now; null: the file's own bottom
  picked: boolean
  own: { lay: Lay; down?: number[]; normal: number[] | null; why: 'flat' | 'file' | 'plate' }
}
export interface SidesView { id: string; parts: SidePart[]; from: string | null }
/** A pick as the box takes it (PUT …/side): auto hands the part back to its own way. */
export interface SidePick { part: number; lay: 'auto' | 'file' | 'side'; down?: number[] }

/** "0-bushing.stl" → "Bushing": a part as a person calls it. */
export function partName(name: string): string {
  const s = name.replace(/^\d+-/, '').replace(/\.(stl|obj|3mf|step|stp)$/i, '').replace(/_+/g, ' ').trim() || 'Part'
  return s[0].toUpperCase() + s.slice(1)
}

/** The tag on the side a part goes back to by itself. */
export function ownTag(p: SidePart, from: string | null): string | null {
  if (p.own.why === 'plate') return from ? `as ${from} printed it` : 'as it printed'
  return p.own.why === 'flat' ? 'laid flat for you' : null
}

/** The sides to pick from for one part, its own tagged. */
export function partOptions(p: SidePart, from: string | null): SideOption[] {
  const tag = ownTag(p, from)
  return sideOptions(p.lying, p.normal, tag ? { normal: p.own.normal, tag } : undefined)
}

/** One part's side, in words: what's down, and what touches. */
export function partWords(p: SidePart, from: string | null): { value: string; line: string } {
  const line = sideLine(p.lying, p.normal)
  if (p.picked) {
    const value = p.lay === 'file' ? 'As in the file' : p.lay === 'flat' ? 'Its flattest side' : 'The side you picked'
    return { value, line }
  }
  if (p.own.why === 'plate') return { value: from ? `As ${from} printed it` : 'As it last printed', line }
  if (p.own.why === 'flat') return { value: 'Laid flat for you', line: line ? `Its flattest side · ${line}` : 'Its flattest side' }
  return { value: 'As in the file', line: (p.lying?.sides?.length ?? 0) > 1 ? line : 'It only sits one way' }
}

/** The Lying tile on the model page and the row on the plan's move sheet. */
export function sideRow(v: SidesView | null): { value: string; line: string } {
  if (!v) return { value: 'Reading it…', line: 'Which side goes down' }
  if (v.parts.length === 1) return partWords(v.parts[0], v.from)
  const k = v.parts.filter((p) => p.picked).length
  return { value: k ? `${k} on a side you picked` : "Each part's own", line: `${v.parts.length} parts, each on its own side` }
}

/** Whether there's anything to pick: some part rests on more than one side. */
export const canPickSide = (v: SidesView | null) => !!v?.parts.some((p) => (p.lying?.sides?.length ?? 0) > 1)

/** What a setup is sliced with: a new side is a new setup. */
export const sidesKey = (v: SidesView | null) => (v ? v.parts.map((p) => (p.normal ? p.normal.map((x) => x.toFixed(3)).join(',') : 'file')).join(';') : '')

/** The pick to send for a side tapped on part n (null: the file's own bottom). */
export const pickOf = (n: number, normal: number[] | null): SidePick => (normal ? { part: n, lay: 'side', down: normal } : { part: n, lay: 'file' })

/** The view with a side tapped, shown at once while the box keeps it: the part's own way is no pick at all. */
export function withSide(v: SidesView, n: number, normal: number[] | null): SidesView {
  return {
    ...v,
    parts: v.parts.map((p) => {
      if (p.n !== n) return p
      const own = normal == null ? p.own.normal == null : sameSide(normal, p.own.normal)
      if (own) return { ...p, lay: p.own.lay, down: p.own.down, normal: p.own.normal, picked: false }
      const flat = sameSide(normal, p.lying?.flat_normal)
      return { ...p, lay: normal == null ? 'file' : flat ? 'flat' : 'side', down: normal ?? undefined, normal, picked: true }
    }),
  }
}

/** The model's picture with each part on its side: one part turned; several laid out on the plate, as the printer's
 *  Print draws a plate, once any is turned (as the file has them otherwise). */
export function laidPicture(parts: (Float32Array | null)[], v: SidesView | null): Float32Array | null {
  const have = parts.filter((t): t is Float32Array => !!t)
  if (!have.length) return null
  const turned = parts.map((t, i) => {
    const normal = v?.parts[i]?.normal
    return t && normal ? layOn(t, normal) : t
  })
  if (parts.length === 1) return turned[0]
  if (!v?.parts.some((p) => p.normal)) return concat(have)
  const plate = turned.map((tris) => ({ tris, copies: 1, scale: 1 }))
  return compose(plate, provisional(plate, null))
}

function concat(all: Float32Array[]): Float32Array {
  const out = new Float32Array(all.reduce((n, a) => n + a.length, 0))
  let at = 0
  for (const a of all) { out.set(a, at); at += a.length }
  return out
}
