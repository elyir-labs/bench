// Painting and a change at a height (design/paint-and-height/, picked 21 October 2026: height C with A's line,
// painting A). A part's paint is a color per triangle: 0 is the part's own, k is the plate's color k - 1. A change
// at a height is the whole plate's: from z up it prints in another of the plate's colors. Pure functions, so
// tests/paint.test.ts can pin them.

export interface Height { z: number; spool: number }

const EPS = 0.01

function zRange(tris: Float32Array): [number, number] {
  let lo = Infinity, hi = -Infinity
  for (let i = 2; i < tris.length; i += 3) { if (tris[i] < lo) lo = tris[i]; if (tris[i] > hi) hi = tris[i] }
  return [lo, hi]
}

function normalArea(tris: Float32Array, t: number): [number, number, number, number] {
  const i = t * 9
  const ux = tris[i + 3] - tris[i], uy = tris[i + 4] - tris[i + 1], uz = tris[i + 5] - tris[i + 2]
  const vx = tris[i + 6] - tris[i], vy = tris[i + 7] - tris[i + 1], vz = tris[i + 8] - tris[i + 2]
  const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx
  const l = Math.hypot(nx, ny, nz)
  return l ? [nx / l, ny / l, nz / l, l / 2] : [0, 0, 0, 0]
}

/** Where something new starts on top of a flat area (C, "Bench spots it"): the height, in mm above the plate at
 *  this scale, of the biggest area facing straight up that has more of the part above it. Only when that area is
 *  at least a quarter of the part's footprint (not a hat's brim on a figure), and there's at least a layer or two
 *  either side of it. Area
 *  facing down at the same height is taken off: letters made as bodies of their own stand on the plate's top, which
 *  stays one big face in the file. `raised`: what's above is short (letters on a sign), not most of the part (a
 *  figure on its base). */
export function flatTop(tris: Float32Array, scale = 1): { z: number; raised: boolean } | null {
  const n = tris.length / 9
  if (!n) return null
  const [lo, hi] = zRange(tris)
  const height = (hi - lo) * scale
  const up = new Map<number, number>()
  const down = new Map<number, number>()
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity
  for (let i = 0; i < tris.length; i += 3) {
    if (tris[i] < x0) x0 = tris[i]; if (tris[i] > x1) x1 = tris[i]
    if (tris[i + 1] < y0) y0 = tris[i + 1]; if (tris[i + 1] > y1) y1 = tris[i + 1]
  }
  const footprint = (x1 - x0) * (y1 - y0) * scale * scale
  for (let t = 0; t < n; t++) {
    const [, , nz, a] = normalArea(tris, t)
    const i = t * 9
    const z = (Math.max(tris[i + 2], tris[i + 5], tris[i + 8]) - lo) * scale
    const flat = Math.abs(tris[i + 2] - tris[i + 5]) < EPS && Math.abs(tris[i + 2] - tris[i + 8]) < EPS
    if (!flat) continue
    const k = Math.round(z * 20) / 20
    if (nz < -0.999 && z < EPS) continue
    else if (nz < -0.999) down.set(k, (down.get(k) ?? 0) + a * scale * scale)
    else if (nz > 0.999) up.set(k, (up.get(k) ?? 0) + a * scale * scale)
  }
  let best: { z: number; area: number } | null = null
  for (const [z, all] of up) {
    const area = all - (down.get(z) ?? 0)
    if (z < 0.6 || height - z < 0.4 || area < footprint * 0.25) continue
    if (!best || area > best.area) best = { z, area }
  }
  return best ? { z: best.z, raised: height - best.z <= Math.max(6, height * 0.4) } : null
}

/** Each triangle's color from the changes at a height: the part's own below the first, then each change's from its
 *  height up, by where the triangle's middle is (a flat top at exactly the height keeps the color below). */
export function heightColors(tris: Float32Array, heights: Height[], scale = 1, own = 0): Uint8Array {
  const n = tris.length / 9
  const out = new Uint8Array(n).fill(own + 1)
  if (!heights.length) return out
  const [lo] = zRange(tris)
  const sorted = [...heights].sort((a, b) => a.z - b.z)
  for (let t = 0; t < n; t++) {
    const i = t * 9
    const mid = ((tris[i + 2] + tris[i + 5] + tris[i + 8]) / 3 - lo) * scale
    for (const h of sorted) if (mid > h.z + EPS) out[t] = h.spool + 1
  }
  return out
}

/** Which triangles share each edge: for each triangle, its up to three neighbours (-1 where none). */
export function neighbours(tris: Float32Array): Int32Array {
  const n = tris.length / 9
  const out = new Int32Array(n * 3).fill(-1)
  const key = (a: number, b: number) => {
    const p = [tris[a], tris[a + 1], tris[a + 2]].map(v => Math.round(v * 1000)).join(',')
    const q = [tris[b], tris[b + 1], tris[b + 2]].map(v => Math.round(v * 1000)).join(',')
    return p < q ? `${p}|${q}` : `${q}|${p}`
  }
  const open = new Map<string, number>()
  for (let t = 0; t < n; t++) {
    for (let e = 0; e < 3; e++) {
      const k = key(t * 9 + e * 3, t * 9 + ((e + 1) % 3) * 3)
      const other = open.get(k)
      if (other === undefined) { open.set(k, t * 3 + e); continue }
      open.delete(k)
      const u = Math.floor(other / 3)
      out[t * 3 + e] = u
      out[other] = t
    }
  }
  return out
}

/** "Up to an edge": from the tapped triangle across its neighbours while the surface bends less than `angle`
 *  degrees from one triangle to the next, as Orca's smart fill does. A box's lid is one tap; so is a hat. */
export function fillFrom(tris: Float32Array, near: Int32Array, start: number, angle = 30): number[] {
  const cos = Math.cos((angle * Math.PI) / 180)
  const seen = new Uint8Array(tris.length / 9)
  const out: number[] = []
  const stack = [start]
  seen[start] = 1
  while (stack.length) {
    const t = stack.pop()!
    out.push(t)
    const [ax, ay, az] = normalArea(tris, t)
    for (let e = 0; e < 3; e++) {
      const u = near[t * 3 + e]
      if (u < 0 || seen[u]) continue
      const [bx, by, bz] = normalArea(tris, u)
      if (ax * bx + ay * by + az * bz < cos) continue
      seen[u] = 1
      stack.push(u)
    }
  }
  return out
}

function middle(tris: Float32Array, t: number): [number, number, number] {
  const i = t * 9
  return [(tris[i] + tris[i + 3] + tris[i + 6]) / 3, (tris[i + 1] + tris[i + 4] + tris[i + 7]) / 3, (tris[i + 2] + tris[i + 5] + tris[i + 8]) / 3]
}

/** "Just a spot": the tapped triangle and its neighbours whose middles are within `radius` mm of its own. */
export function spotFrom(tris: Float32Array, near: Int32Array, start: number, radius = 3): number[] {
  const [cx, cy, cz] = middle(tris, start)
  const seen = new Uint8Array(tris.length / 9)
  const out: number[] = []
  const stack = [start]
  seen[start] = 1
  while (stack.length) {
    const t = stack.pop()!
    out.push(t)
    for (let e = 0; e < 3; e++) {
      const u = near[t * 3 + e]
      if (u < 0 || seen[u]) continue
      const [x, y, z] = middle(tris, u)
      if (Math.hypot(x - cx, y - cy, z - cz) > radius) continue
      seen[u] = 1
      stack.push(u)
    }
  }
  return out
}

/** Paint as the slicer takes it: [color, count, ...]. Nothing painted is null. */
export function toRuns(states: Uint8Array): number[] | null {
  if (!states.some(s => s)) return null
  const out: number[] = []
  for (let t = 0; t < states.length; t++) {
    if (out.length && out[out.length - 2] === states[t]) out[out.length - 1]++
    else out.push(states[t], 1)
  }
  return out
}

/** Colors as runs of triangles to draw: each run ends before triangle `end`. `color` turns a state into a color. */
export function drawRuns(states: Uint8Array, color: (state: number) => string): { end: number; color: string }[] {
  const out: { end: number; color: string }[] = []
  for (let t = 0; t < states.length; t++) {
    const c = color(states[t])
    if (out.length && out[out.length - 1].color === c) out[out.length - 1].end = t + 1
    else out.push({ end: t + 1, color: c })
  }
  return out
}

/** The plate's colors a part's paint uses, 0-based. */
export function paintUses(states: Uint8Array | null | undefined): Set<number> {
  const out = new Set<number>()
  if (states) for (const s of states) if (s) out.add(s - 1)
  return out
}

/** The layer a height lands on, as Orca will print it: the first layer that starts at or above z. Returns that
 *  layer's start (where the color begins), its number counted from 1, and how many layers the part has. */
export function snapToLayer(z: number, top: number, first = 0.2, layer = 0.2): { z: number; n: number; of: number } {
  const n = Math.max(0, Math.ceil((z - first) / layer - 1e-6))
  const start = Math.round((first + n * layer) * 1000) / 1000
  const of = 1 + Math.max(0, Math.ceil((top - first) / layer - 1e-6))
  return { z: start, n: n + 2, of }
}

/** "3.2 mm" */
export function mm(z: number): string {
  return `${Math.round(z * 100) / 100} mm`
}
