// Where supports go (design/supports-where/, A "tap the places", picked 2 November 2026). A part's faces that point
// down, grouped into places a person can name and tap, and its marks: a state per triangle as Orca's paint_supports
// takes them (0 Orca decides, 1 here, 2 not here). Each place is on or off; a mark is kept only where the person
// differs from Orca, so "Where it's needed" sends the marks as they are, and "Only where I say" sends every place
// that's on. Pure, so tests/places.test.ts can pin them.

import { neighbours } from './paint.ts'

export type Where = 'needed' | 'only'
/** A part's own choice on the Where screen: none = no supports on this part (round 2, C). */
export type PartWhere = Where | 'none'
export const HERE = 1, NOT_HERE = 2

export interface Place {
  tris: number[]                 // its triangles, in the part's order
  area: number                   // mm², at the part's scale
  size: [number, number]         // across x and y, mm
  z: number                      // how high its lowest point is above the plate, mm
  lean: number                   // degrees from flat: 0 is a ceiling, 90 a wall
  auto: boolean                  // Orca supports it by itself (leans less than its threshold)
}

const STEEP = 60                 // past this a face is a wall that prints without help: not a place
const BEND = 30                  // as Paint's "up to an edge": one place until the surface bends this much
const ON_PLATE = 0.05

/** The places that point down on a part as it prints, biggest first. threshold: Orca's support_threshold_angle,
 *  measured from flat (it supports what leans less). Places smaller than minArea mm² are left to Orca. */
export function places(tris: Float32Array, scale = 1, threshold = 30, minArea = 4, max = 12): Place[] {
  const n = tris.length / 9
  if (!n) return []
  let lo = Infinity
  for (let i = 2; i < tris.length; i += 3) if (tris[i] < lo) lo = tris[i]
  const nx = new Float32Array(n), ny = new Float32Array(n), nz = new Float32Array(n), area = new Float32Array(n)
  const down = new Uint8Array(n)
  const steep = -Math.cos((STEEP * Math.PI) / 180)
  for (let t = 0; t < n; t++) {
    const i = t * 9
    const ux = tris[i + 3] - tris[i], uy = tris[i + 4] - tris[i + 1], uz = tris[i + 5] - tris[i + 2]
    const vx = tris[i + 6] - tris[i], vy = tris[i + 7] - tris[i + 1], vz = tris[i + 8] - tris[i + 2]
    const cx = uy * vz - uz * vy, cy = uz * vx - ux * vz, cz = ux * vy - uy * vx
    const l = Math.hypot(cx, cy, cz)
    if (!l) continue
    nx[t] = cx / l; ny[t] = cy / l; nz[t] = cz / l; area[t] = (l / 2) * scale * scale
    const onPlate = Math.max(tris[i + 2], tris[i + 5], tris[i + 8]) - lo < ON_PLATE
    down[t] = nz[t] < steep && !onPlate ? 1 : 0
  }
  const near = neighbours(tris)
  const bend = Math.cos((BEND * Math.PI) / 180)
  const flatEnough = Math.cos(((threshold + 0.5) * Math.PI) / 180)   // a face right at the line counts, as Orca counts it
  const seen = new Uint8Array(n)
  const out: Place[] = []
  for (let s = 0; s < n; s++) {
    if (!down[s] || seen[s]) continue
    const group: number[] = []
    const stack = [s]
    seen[s] = 1
    while (stack.length) {
      const t = stack.pop()!
      group.push(t)
      for (let e = 0; e < 3; e++) {
        const u = near[t * 3 + e]
        if (u < 0 || seen[u] || !down[u]) continue
        if (nx[t] * nx[u] + ny[t] * ny[u] + nz[t] * nz[u] < bend) continue
        seen[u] = 1
        stack.push(u)
      }
    }
    let a = 0, flat = 0, cos = 0, x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity, z0 = Infinity
    for (const t of group) {
      a += area[t]
      cos += -nz[t] * area[t]
      if (-nz[t] >= flatEnough) flat += area[t]
      for (let k = 0; k < 3; k++) {
        const i = t * 9 + k * 3
        x0 = Math.min(x0, tris[i]); x1 = Math.max(x1, tris[i])
        y0 = Math.min(y0, tris[i + 1]); y1 = Math.max(y1, tris[i + 1])
        z0 = Math.min(z0, tris[i + 2])
      }
    }
    if (a < minArea) continue
    out.push({ tris: group, area: a, size: [(x1 - x0) * scale, (y1 - y0) * scale], z: (z0 - lo) * scale,
      lean: (Math.acos(Math.min(1, cos / a)) * 180) / Math.PI, auto: flat >= a / 2 })
  }
  return out.sort((p, q) => q.area - p.area).slice(0, max)
}

/** Whether a place gets supports: marked here, or Orca's own and not marked "not here". */
export function isOn(place: Place, marks: Uint8Array | null): boolean {
  let here = 0, not = 0
  if (marks) for (const t of place.tris) { if (marks[t] === HERE) here++; else if (marks[t] === NOT_HERE) not++ }
  const half = place.tris.length / 2
  return here > half || (place.auto && not <= half)
}

/** Marks with a place switched: only what differs from Orca is kept. */
export function turned(place: Place, marks: Uint8Array | null, n: number, on: boolean): Uint8Array {
  const out = marks?.length === n ? marks.slice() : new Uint8Array(n)
  const to = on === place.auto ? 0 : on ? HERE : NOT_HERE
  for (const t of place.tris) out[t] = to
  return out
}

/** What goes to the slicer: as marked (Orca decides the rest), or "only": every place that's on marked here, and
 *  anything marked here outside the places (a 3MF's own). */
export function marksToSend(marks: Uint8Array | null, found: Place[], where: Where, n: number): Uint8Array | null {
  if (where === 'needed') return marks?.length === n && marks.some(v => v) ? marks : null
  const out = new Uint8Array(n)
  if (marks?.length === n) for (let t = 0; t < n; t++) if (marks[t] === HERE) out[t] = HERE
  for (const p of found) if (isOn(p, marks)) for (const t of p.tris) out[t] = HERE
  return out.some(v => v) ? out : null
}

/** How a part's places differ from Orca's choice. */
export function changed(found: Place[], marks: Uint8Array | null): { added: number; off: number } {
  let added = 0, off = 0
  for (const p of found) {
    const on = isOn(p, marks)
    if (on && !p.auto) added++
    if (!on && p.auto) off++
  }
  return { added, off }
}

/** Marks no longer on a place that points down (the part was turned since), in mm² at the part's scale. */
export function strayArea(tris: Float32Array, marks: Uint8Array | null, found: Place[], scale = 1): number {
  if (!marks || marks.length !== tris.length / 9) return 0
  const inPlace = new Uint8Array(marks.length)
  for (const p of found) for (const t of p.tris) inPlace[t] = 1
  let a = 0
  for (let t = 0; t < marks.length; t++) {
    if (!marks[t] || inPlace[t]) continue
    const i = t * 9
    const ux = tris[i + 3] - tris[i], uy = tris[i + 4] - tris[i + 1], uz = tris[i + 5] - tris[i + 2]
    const vx = tris[i + 6] - tris[i], vy = tris[i + 7] - tris[i + 1], vz = tris[i + 8] - tris[i + 2]
    a += (Math.hypot(uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx) / 2) * scale * scale
  }
  return a
}

/** "Flat underside" / "Leans 40°" */
export function placeName(p: Place): string {
  return p.lean < 5 ? 'Flat underside' : `Leans ${Math.round(p.lean)}°`
}

const mm = (v: number) => (v >= 10 ? Math.round(v) : Math.round(v * 10) / 10)

/** "60 × 40 mm · 40 mm up" */
export function placeSize(p: Place): string {
  const up = p.z < 1 ? 'just above the plate' : `${mm(p.z)} mm up`
  return `${mm(p.size[0])} × ${mm(p.size[1])} mm · ${up}`
}

/** Who chose: "Orca holds it up" / "you took it off" / "Orca leaves it" / "you added it". */
export function placeWho(p: Place, on: boolean): string {
  if (p.auto) return on ? 'Orca holds it up' : 'You took it off'
  return on ? 'You added it' : 'Prints without · may come out rough'
}

/** [state, count, ...] from the slicer, as a state per triangle; null when it doesn't fit the part. */
export function fromRuns(runs: number[] | null | undefined, n: number): Uint8Array | null {
  if (!runs?.length) return null
  const out = new Uint8Array(n)
  let t = 0
  for (let k = 0; k + 1 < runs.length; k += 2) {
    for (let j = 0; j < runs[k + 1]; j++) { if (t >= n) return null; out[t++] = runs[k] }
  }
  return t === n ? out : null
}
