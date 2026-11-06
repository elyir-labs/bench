// Any side down (design/any-side/, C): a side tapped on the picture, or the part turned a quarter at a time. The sheet
// keeps the whole pose, so turns carry on from what the picture shows; the slicer only needs the file's own direction
// that ends up down (its `down`). Pure, so tests can pin the turns.

import { downRotation, sizeOf, turnTo } from './stl.ts'

export type Turn = 'flip' | 'rollLeft' | 'rollRight' | 'tipForward' | 'tipBack'
/** A rotation from the file's own terms to the plate's. */
export type Pose = number[][]

const UP = [0, 0, 1]
const dot = (a: number[], b: number[]) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
const cross = (a: number[], b: number[]) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
const unit = (v: number[]) => { const l = Math.hypot(v[0], v[1], v[2]) || 1; return v.map(x => x / l) }
const times = (a: Pose, b: Pose): Pose => a.map(row => [0, 1, 2].map(j => row[0] * b[0][j] + row[1] * b[1][j] + row[2] * b[2][j]))
const clean = (p: Pose): Pose => p.map(row => row.map(x => (Math.abs(x) < 1e-9 ? 0 : Math.abs(Math.abs(x) - 1) < 1e-9 ? Math.sign(x) : x)))

function about(axis: number[], angle: number): Pose {
  const [x, y, z] = axis, c = Math.cos(angle), s = Math.sin(angle), k = 1 - c
  return [[c + x * x * k, x * y * k - z * s, x * z * k + y * s], [y * x * k + z * s, c + y * y * k, y * z * k - x * s], [z * x * k - y * s, z * y * k + x * s, c + z * z * k]]
}

/** The pose with the file's `down` on the plate (null: as in the file), as the slicer would lay it. */
export const poseOf = (down: number[] | null): Pose => (down ? downRotation(down) : [[1, 0, 0], [0, 1, 0], [0, 0, 1]])

/** The file's own direction that's down in this pose; null when that's the file's own bottom. Rounded, so turns
 *  that come back to a side say exactly the same direction. */
export function downOf(p: Pose): number[] | null {
  const d = unit([-p[2][0], -p[2][1], -p[2][2]]).map(x => (Math.abs(x) < 1e-6 ? 0 : Math.round(x * 1e5) / 1e5))
  return d[2] < -0.99999 ? null : d
}

/** The plate's own axes nearest to looking into the picture from the camera at `az`, and across it. */
function axes(az: number) {
  const into = [Math.sin(az), Math.cos(az), 0]
  const f = [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0]].reduce((a, b) => (dot(b, into) > dot(a, into) ? b : a))
  return { f, r: cross(f, UP) }
}

/** The pose after a turn, seen from `az` (ModelPicture's view): roll moves the top across the picture, tip moves it
 *  towards or away from you, flip turns it over. */
export function turn(p: Pose, t: Turn, az: number): Pose {
  const { f, r } = axes(az)
  const [axis, angle] = t === 'flip' ? [r, Math.PI] : t === 'rollRight' ? [f, Math.PI / 2] : t === 'rollLeft' ? [f, -Math.PI / 2]
    : t === 'tipForward' ? [r, Math.PI / 2] : [r, -Math.PI / 2]
  return clean(times(about(axis, angle), p))
}

/** The pose with a side seen in the picture (its outward normal, in the plate's terms) turned onto the plate. */
export const onto = (p: Pose, normal: number[]): Pose => clean(times(downRotation(normal), p))

/** A turn that ends just off a flat facet of the part, one within `within` degrees of the plate where it touches,
 *  settles onto it: a round part rolled a quarter turn would otherwise balance on the edge between two facets. */
export function settle(p: Pose, file: Float32Array, within = 10): Pose {
  const t = posed(file, p)
  let zmin = Infinity
  for (let i = 2; i < t.length; i += 3) zmin = Math.min(zmin, t[i])
  let best: number[] | null = null, most = Math.cos((within * Math.PI) / 180)
  for (let i = 0; i < t.length / 9; i++) {
    const n = normalOf(t, i)
    if (!n || -n[2] <= most || (t[i * 9 + 2] + t[i * 9 + 5] + t[i * 9 + 8]) / 3 - zmin > 1) continue
    most = -n[2]; best = n
  }
  return best && most < 0.99999 ? onto(p, best) : p
}

/** The flat face triangle t is part of: its outward normal and every triangle on it. */
export function faceAt(tris: Float32Array, t: number): { normal: number[]; members: number[] } | null {
  const n = normalOf(tris, t)
  if (!n) return null
  const plane = dot(n, [tris[t * 9], tris[t * 9 + 1], tris[t * 9 + 2]])
  const members: number[] = []
  for (let i = 0; i < tris.length / 9; i++) {
    const m = normalOf(tris, i)
    if (!m || dot(m, n) < 0.996) continue
    let on = true
    for (let k = 0; k < 3 && on; k++) on = Math.abs(dot(n, [tris[i * 9 + k * 3], tris[i * 9 + k * 3 + 1], tris[i * 9 + k * 3 + 2]]) - plane) < 0.05
    if (on) members.push(i)
  }
  return { normal: n, members }
}

function normalOf(tris: Float32Array, t: number): number[] | null {
  const i = t * 9
  const a = [tris[i], tris[i + 1], tris[i + 2]]
  const n = cross([tris[i + 3] - a[0], tris[i + 4] - a[1], tris[i + 5] - a[2]], [tris[i + 6] - a[0], tris[i + 7] - a[1], tris[i + 8] - a[2]])
  return Math.hypot(n[0], n[1], n[2]) < 1e-12 ? null : unit(n)
}

/** The same triangles with `members` moved to the end, so a picture can draw them in another color past `end`. */
export function lit(tris: Float32Array, members: number[]): { tris: Float32Array; end: number } {
  const on = new Uint8Array(tris.length / 9)
  for (const m of members) on[m] = 1
  const out = new Float32Array(tris.length)
  let at = 0
  for (const pass of [0, 1]) for (let t = 0; t < on.length; t++) if (on[t] === pass) { out.set(tris.subarray(t * 9, t * 9 + 9), at); at += 9 }
  return { tris: out, end: on.length - members.length }
}

/** The model in this pose, set down on the plate. */
export const posed = (file: Float32Array, p: Pose) => turnTo(file, p)

/** How it stands, already posed: how tall, and how much touches the plate (mm²). */
export function standing(t: Float32Array): { tall: number; touches: number } {
  let zmin = Infinity
  for (let i = 2; i < t.length; i += 3) zmin = Math.min(zmin, t[i])
  let touches = 0
  for (let i = 0; i < t.length; i += 9) {
    if (Math.abs(t[i + 2] - zmin) > 0.05 || Math.abs(t[i + 5] - zmin) > 0.05 || Math.abs(t[i + 8] - zmin) > 0.05) continue
    touches += Math.abs((t[i + 3] - t[i]) * (t[i + 7] - t[i + 1]) - (t[i + 6] - t[i]) * (t[i + 4] - t[i + 1])) / 2
  }
  return { tall: sizeOf(t)?.[2] ?? 0, touches }
}
