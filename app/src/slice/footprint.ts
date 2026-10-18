// A part's first layer seen from above, with the brim it would get (design/brim/, A): measured from the
// triangles that lie on the plate, not sliced, so the Brim sheet opens at once and the slice waits for a pick.

export type BrimKind = 'none' | 'ears' | 'all'
export type Box = [number, number, number, number]   // x0, y0, x1, y1 in mm

export interface Footprint {
  tris: number[]          // the triangles on the plate, flat in 2D: [x0, y0, x1, y1, x2, y2, ...]
  outer: number[][]       // each island's outside edge, a loop [x0, y0, x1, y1, ...]
  holes: number[][]       // edges inside an island (a window, a screw hole): no brim there
  corners: number[][]     // [x, y] on an outside edge sharper than EAR_ANGLE: where corner pads go
  box: Box
}

export const BRIM_MM = 5        // Orca's brim_width in Workshop's preset
export const EAR_ANGLE = 125    // Orca's brim_ears_max_angle: a corner sharper than this gets a pad

const key = (x: number, y: number) => `${Math.round(x * 100)},${Math.round(y * 100)}`

/** The footprint of a part as it will print (tris from session's Part.tris), at `scale`. null when nothing
 *  lies flat on the plate (standing on an edge). */
export function footprint(tris: Float32Array, scale = 1, tol = 0.05): Footprint | null {
  let zmin = Infinity
  for (let i = 2; i < tris.length; i += 3) zmin = Math.min(zmin, tris[i])
  const flat: number[] = []
  const at = new Map<string, [number, number]>()
  const next = new Map<string, string[]>()           // directed edges, every triangle anticlockwise
  const angle = new Map<string, number>()            // the angle inside the shape at each corner, summed
  for (let t = 0; t + 8 < tris.length; t += 9) {
    if (Math.abs(tris[t + 2] - zmin) > tol || Math.abs(tris[t + 5] - zmin) > tol || Math.abs(tris[t + 8] - zmin) > tol) continue
    let p = [[tris[t], tris[t + 1]], [tris[t + 3], tris[t + 4]], [tris[t + 6], tris[t + 7]]].map(([x, y]) => [x * scale, y * scale])
    const a2 = (p[1][0] - p[0][0]) * (p[2][1] - p[0][1]) - (p[2][0] - p[0][0]) * (p[1][1] - p[0][1])
    if (Math.abs(a2) < 1e-9) continue
    if (a2 < 0) p = [p[0], p[2], p[1]]
    flat.push(...p.flat())
    const k = p.map(([x, y]) => key(x, y))
    for (let i = 0; i < 3; i++) {
      at.set(k[i], p[i] as [number, number])
      const list = next.get(k[i]) ?? []
      list.push(k[(i + 1) % 3])
      next.set(k[i], list)
      const [o, a, b] = [p[i], p[(i + 1) % 3], p[(i + 2) % 3]]
      const v1 = [a[0] - o[0], a[1] - o[1]], v2 = [b[0] - o[0], b[1] - o[1]]
      const cos = (v1[0] * v2[0] + v1[1] * v2[1]) / (Math.hypot(...v1) * Math.hypot(...v2) || 1)
      angle.set(k[i], (angle.get(k[i]) ?? 0) + Math.acos(Math.max(-1, Math.min(1, cos))) * 180 / Math.PI)
    }
  }
  if (!flat.length) return null
  // the edges with no triangle on their other side are the outline; followed round, they make loops
  const edge = new Map<string, string[]>()
  for (const [a, list] of next) for (const b of list) if (!(next.get(b) ?? []).includes(a)) edge.set(a, [...(edge.get(a) ?? []), b])
  const outer: number[][] = [], holes: number[][] = [], corners: number[][] = []
  for (const start of [...edge.keys()]) {
    if (!edge.get(start)?.length) continue
    const loop: string[] = []
    let cur = start
    while (edge.get(cur)?.length && loop.length <= edge.size + 1) {
      loop.push(cur)
      cur = edge.get(cur)!.shift()!
      if (cur === start) break
    }
    if (loop.length < 3) continue
    const pts = loop.flatMap(k => at.get(k)!)
    let a2 = 0
    for (let i = 0; i < loop.length; i++) {
      const j = (i + 1) % loop.length
      a2 += pts[2 * i] * pts[2 * j + 1] - pts[2 * j] * pts[2 * i + 1]
    }
    if (a2 > 0) {
      outer.push(pts)
      for (const k of loop) if ((angle.get(k) ?? 180) < EAR_ANGLE) corners.push(at.get(k)!)
    } else holes.push(pts)
  }
  const box: Box = [Infinity, Infinity, -Infinity, -Infinity]
  for (let i = 0; i < flat.length; i += 2) {
    box[0] = Math.min(box[0], flat[i]); box[1] = Math.min(box[1], flat[i + 1])
    box[2] = Math.max(box[2], flat[i]); box[3] = Math.max(box[3], flat[i + 1])
  }
  return { tris: flat, outer, holes, corners, box }
}

/** The box every picture of one part shares, with room for a brim all round, so the three can be compared. */
export const roomFor = (f: Footprint): Box => [f.box[0] - BRIM_MM - 1, f.box[1] - BRIM_MM - 1, f.box[2] + BRIM_MM + 1, f.box[3] + BRIM_MM + 1]

/** Draw a footprint into a canvas already sized in device pixels: the part solid, its brim see-through,
 *  the front of the plate at the bottom. */
export function drawFootprint(canvas: HTMLCanvasElement, f: Footprint, color: string, kind: BrimKind, box: Box = roomFor(f)): void {
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const W = canvas.width, H = canvas.height
  ctx.clearRect(0, 0, W, H)
  const s = Math.min(W / (box[2] - box[0]), H / (box[3] - box[1]))
  const ox = (W - (box[2] - box[0]) * s) / 2, oy = (H - (box[3] - box[1]) * s) / 2
  const X = (x: number) => ox + (x - box[0]) * s, Y = (y: number) => oy + (box[3] - y) * s
  const loop = (c: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D, pts: number[]) => {
    c.moveTo(X(pts[0]), Y(pts[1]))
    for (let i = 2; i < pts.length; i += 2) c.lineTo(X(pts[i]), Y(pts[i + 1]))
    c.closePath()
  }
  if (kind !== 'none') {
    // drawn whole on a layer of its own, then laid down see-through, so overlaps don't darken
    const layer = document.createElement('canvas')
    layer.width = W; layer.height = H
    const b = layer.getContext('2d')!
    b.fillStyle = b.strokeStyle = color
    b.beginPath()
    if (kind === 'all') {
      for (const pts of f.outer) loop(b, pts)
      b.fill()
      b.lineWidth = 2 * BRIM_MM * s; b.lineJoin = 'round'
      b.stroke()
      b.globalCompositeOperation = 'destination-out'
      b.beginPath()
      for (const pts of f.holes) loop(b, pts)
      b.fill()
    } else {
      for (const [x, y] of f.corners) { b.moveTo(X(x) + BRIM_MM * s, Y(y)); b.arc(X(x), Y(y), BRIM_MM * s, 0, 2 * Math.PI) }
      b.fill()
    }
    ctx.globalAlpha = 0.38
    ctx.drawImage(layer, 0, 0)
    ctx.globalAlpha = 1
  }
  ctx.fillStyle = ctx.strokeStyle = color
  ctx.lineWidth = Math.max(0.5, s * 0.05)
  ctx.beginPath()
  for (let i = 0; i < f.tris.length; i += 6) {
    ctx.moveTo(X(f.tris[i]), Y(f.tris[i + 1])); ctx.lineTo(X(f.tris[i + 2]), Y(f.tris[i + 3])); ctx.lineTo(X(f.tris[i + 4]), Y(f.tris[i + 5]))
    ctx.closePath()
  }
  ctx.fill()
  ctx.stroke()       // closes the hairlines between triangles
}
