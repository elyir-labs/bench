// The model, drawn in the spool's colour from above and to the front, the way a slicer's preview
// looks. A painter's sort on a 2D canvas: no WebGL, no library, and fast enough for the tens of
// thousands of triangles a downloaded part has. The same drawing becomes the file's thumbnail.

import type { SupportLines } from './supports'
import type { LayerPaths, LayerStack } from '../look/layers'

export interface View { az?: number; el?: number }
/** plate: draw the build plate under the model, so which side is down is plain to see.
 *  bed: the printer's bed [x, y] in mm, for a plate of several parts placed in bed coordinates: when they
 *  spread over much of it, the whole bed is drawn (design/plate/). fast: fill only, while it's being turned. */
export interface DrawOptions { plate?: boolean; plateColor?: string; gridColor?: string; bed?: number[] | null; fast?: boolean
  /** zoom: times bigger than fitting (design/ready-wide/); shift: move the centre across, in device pixels
   *  (left of a card that covers the right of the picture). */
  zoom?: number; shift?: number
  /** supports: the slice's support lines, drawn solid under a see-through part (design/supports/, A).
   *  ghost: how opaque the part is then, 0 to 1. */
  supports?: SupportLines | null; supportColor?: string; ghost?: number
  /** runs: a color per run of triangles (each run ends before triangle `end`), for a plate of several colors
   *  (design/multi-color/); `color` is used past the last run. */
  runs?: Run[] }
export interface Run { end: number; color: string }

/** Each triangle turned towards the camera: screen corners, depth, and how much light it gets. */
export function project(tris: Float32Array, { az = -0.6, el = 0.62 }: View = {}) {
  const ca = Math.cos(az), sa = Math.sin(az), ce = Math.cos(el), se = Math.sin(el)
  const n = tris.length / 9
  const pts = new Float32Array(n * 6)       // x0, y0, x1, y1, x2, y2 on screen (y down)
  const depth = new Float32Array(n)
  const light = new Float32Array(n)
  const keep = new Uint8Array(n)
  // light from the camera's upper left
  const L = norm([-0.45, -0.75, 0.6])
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
  for (let t = 0; t < n; t++) {
    const v: number[][] = []
    for (let k = 0; k < 3; k++) {
      const i = t * 9 + k * 3
      const x = tris[i], y = tris[i + 1], z = tris[i + 2]
      const x1 = x * ca - y * sa, y1 = x * sa + y * ca            // turn about the vertical
      const y2 = y1 * ce - z * se, z2 = y1 * se + z * ce          // tilt to look down on it
      v.push([x1, y2, z2])
    }
    const e1 = sub(v[1], v[0]), e2 = sub(v[2], v[0])
    const nrm = norm(cross(e1, e2))
    if (nrm[1] >= 0) continue                                    // faces away from the camera (at -y)
    keep[t] = 1
    depth[t] = (v[0][1] + v[1][1] + v[2][1]) / 3
    light[t] = Math.max(0, nrm[0] * L[0] + nrm[1] * L[1] + nrm[2] * L[2])
    for (let k = 0; k < 3; k++) {
      const sx = v[k][0], sy = -v[k][2]
      pts[t * 6 + k * 2] = sx; pts[t * 6 + k * 2 + 1] = sy
      if (sx < minX) minX = sx; if (sx > maxX) maxX = sx
      if (sy < minY) minY = sy; if (sy > maxY) maxY = sy
    }
  }
  return { n, pts, depth, light, keep, box: [minX, minY, maxX, maxY] as const }
}

/** A square of plate under the model, a little wider than it, as two triangles facing up. With the bed
 *  given and the model spread over more than half of it, the whole bed instead. */
export function plateUnder(tris: Float32Array, margin = 0.35, bed?: number[] | null): Float32Array {
  let x0 = Infinity, y0 = Infinity, z0 = Infinity, x1 = -Infinity, y1 = -Infinity
  for (let i = 0; i < tris.length; i += 3) {
    x0 = Math.min(x0, tris[i]); x1 = Math.max(x1, tris[i])
    y0 = Math.min(y0, tris[i + 1]); y1 = Math.max(y1, tris[i + 1])
    z0 = Math.min(z0, tris[i + 2])
  }
  let a: number[], b: number[]
  if (bed && bed[0] && bed[1] && (x1 - x0 > bed[0] * 0.5 || y1 - y0 > bed[1] * 0.5)) {
    a = [Math.min(0, x0), Math.min(0, y0)]; b = [Math.max(bed[0], x1), Math.max(bed[1], y1)]
  } else {
    const m = Math.max(x1 - x0, y1 - y0) * margin
    a = [x0 - m, y0 - m]; b = [x1 + m, y1 + m]
  }
  return new Float32Array([a[0], a[1], z0, b[0], a[1], z0, b[0], b[1], z0, a[0], a[1], z0, b[0], b[1], z0, a[0], b[1], z0])
}

/** Where everything lands on a canvas of W x H device pixels: the projection, the scale and the offset. */
function frameOf(tris: Float32Array, W: number, H: number, view: View, pad: number, opts: DrawOptions) {
  const plate = opts.plate ? plateUnder(withLines(tris, opts.supports), 0.35, opts.bed) : null
  const p = project(plate ? concat(tris, plate) : tris, view)
  const sup = opts.supports?.lines.length ? lineView(opts.supports.lines, view) : null
  let [x0, y0, x1, y1] = p.box
  if (sup) { x0 = Math.min(x0, sup.box[0]); y0 = Math.min(y0, sup.box[1]); x1 = Math.max(x1, sup.box[2]); y1 = Math.max(y1, sup.box[3]) }
  const s = Math.min(((W - 2 * Math.abs(opts.shift ?? 0)) * (1 - 2 * pad)) / (x1 - x0 || 1), (H * (1 - 2 * pad)) / (y1 - y0 || 1)) * (opts.zoom ?? 1)
  const ox = (W - (x1 - x0) * s) / 2 - x0 * s + (opts.shift ?? 0), oy = (H - (y1 - y0) * s) / 2 - y0 * s
  return { plate, p, sup, s, ox, oy }
}

/** The model's triangle under a point of the canvas (device pixels), the nearest one when several are, or -1
 *  (design/paint-and-height/, A: a tap paints). The same framing as draw() with the same arguments. */
export function pick(tris: Float32Array, W: number, H: number, x: number, y: number, view: View = {}, pad = 0.1,
  opts: DrawOptions = {}): number {
  if (!tris.length) return -1
  const { p, s, ox, oy } = frameOf(tris, W, H, view, pad, opts)
  const px = (x - ox) / s, py = (y - oy) / s
  let best = -1, depth = Infinity
  for (let t = 0; t < tris.length / 9; t++) {
    if (!p.keep[t] || p.depth[t] >= depth) continue
    const q = t * 6
    const ax = p.pts[q], ay = p.pts[q + 1], bx = p.pts[q + 2], by = p.pts[q + 3], cx = p.pts[q + 4], cy = p.pts[q + 5]
    const d1 = (px - bx) * (ay - by) - (ax - bx) * (py - by)
    const d2 = (px - cx) * (by - cy) - (bx - cx) * (py - cy)
    const d3 = (px - ax) * (cy - ay) - (cx - ax) * (py - ay)
    if ((d1 < 0 || d2 < 0 || d3 < 0) && (d1 > 0 || d2 > 0 || d3 > 0)) continue
    best = t; depth = p.depth[t]
  }
  return best
}

/** Draw into a canvas already sized in device pixels. Transparent around the model. */
export function draw(canvas: HTMLCanvasElement, tris: Float32Array, color: string, view: View = {}, pad = 0.1,
  opts: DrawOptions = {}): void {
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const W = canvas.width, H = canvas.height
  ctx.clearRect(0, 0, W, H)
  if (!tris.length) return
  const { plate, p, sup, s, ox, oy } = frameOf(tris, W, H, view, pad, opts)
  if (plate) {
    // the plate first, flat and quiet, with a grid every 10 mm, then the model's contact shadow on it
    const first = tris.length / 9
    const q = (t: number, k: number) => [p.pts[t * 6 + k * 2] * s + ox, p.pts[t * 6 + k * 2 + 1] * s + oy]
    const corners = [q(first, 0), q(first, 1), q(first, 2), q(first + 1, 2)]
    ctx.beginPath(); corners.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.closePath()
    ctx.fillStyle = opts.plateColor ?? 'rgba(127,127,127,0.18)'; ctx.fill()
    ctx.save(); ctx.clip()
    const proj = projector(view)
    const z = plate[2], gx0 = plate[0], gy0 = plate[1], gx1 = plate[3], gy1 = plate[7]
    ctx.strokeStyle = opts.gridColor ?? 'rgba(127,127,127,0.22)'; ctx.lineWidth = Math.max(1, W / 600)
    for (let g = Math.ceil(gx0 / 10) * 10; g <= gx1; g += 10) line(proj(g, gy0, z), proj(g, gy1, z))
    for (let g = Math.ceil(gy0 / 10) * 10; g <= gy1; g += 10) line(proj(gx0, g, z), proj(gx1, g, z))
    // where the model touches the plate: a soft shadow under the triangles lying on it
    ctx.fillStyle = 'rgba(0,0,0,0.22)'
    for (let t = 0; t < first; t++) {
      const i = t * 9
      if (Math.abs(tris[i + 2] - z) < 0.05 && Math.abs(tris[i + 5] - z) < 0.05 && Math.abs(tris[i + 8] - z) < 0.05) {
        ctx.beginPath()
        const pts = [proj(tris[i], tris[i + 1], z), proj(tris[i + 3], tris[i + 4], z), proj(tris[i + 6], tris[i + 7], z)]
        pts.forEach(([x, y], k) => (k ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.closePath(); ctx.fill()
      }
    }
    ctx.restore()
    function line(a: number[], b: number[]) { ctx!.beginPath(); ctx!.moveTo(a[0], a[1]); ctx!.lineTo(b[0], b[1]); ctx!.stroke() }
    function projector({ az = -0.6, el = 0.62 }: View) {
      const ca = Math.cos(az), sa = Math.sin(az), ce = Math.cos(el), se = Math.sin(el)
      return (x: number, y: number, zz: number) => {
        const y1 = x * sa + y * ca, x1 = x * ca - y * sa
        return [x1 * s + ox, -(y1 * se + zz * ce) * s + oy]
      }
    }
  }
  if (sup && opts.supports) {
    // far first, solid, a little wider than the slicer's line so a thinned-out tree still reads as one
    ctx.strokeStyle = opts.supportColor ?? '#3a4252'
    ctx.lineCap = 'round'
    ctx.lineWidth = Math.max(1, opts.supports.width * s)
    for (const i of sup.order) {
      ctx.beginPath()
      ctx.moveTo(sup.pts[i * 4] * s + ox, sup.pts[i * 4 + 1] * s + oy)
      ctx.lineTo(sup.pts[i * 4 + 2] * s + ox, sup.pts[i * 4 + 3] * s + oy)
      ctx.stroke()
    }
  }
  // a see-through part is drawn whole on a layer of its own and laid over the supports once, so where its
  // triangles overlap it doesn't thicken back to solid
  const layer = sup && opts.ghost != null ? document.createElement('canvas') : null
  let paint: CanvasRenderingContext2D = ctx
  if (layer) { layer.width = W; layer.height = H; paint = layer.getContext('2d') ?? ctx }
  const order: number[] = []
  const modelTris = tris.length / 9
  for (let t = 0; t < modelTris; t++) if (p.keep[t]) order.push(t)
  order.sort((a, b) => p.depth[b] - p.depth[a])                  // far first
  const base = rgb(color)
  const pal = opts.runs?.length ? opts.runs.map(r => rgb(r.color)) : null
  const runOf = pal ? new Uint16Array(modelTris) : null
  if (runOf && opts.runs) {
    let k = 0
    for (let t = 0; t < modelTris; t++) {
      while (k < opts.runs.length && t >= opts.runs[k].end) k++
      runOf[t] = k
    }
  }
  paint.lineJoin = 'round'
  paint.lineWidth = Math.max(0.6, W / 900)                         // hides the hairline seams between triangles
  for (const t of order) {
    const k = 0.42 + 0.58 * p.light[t]
    const [r, g, b] = (pal && runOf ? pal[runOf[t]] : undefined) ?? base
    const c = `rgb(${Math.round(r * k)},${Math.round(g * k)},${Math.round(b * k)})`
    const q = t * 6
    paint.beginPath()
    paint.moveTo(p.pts[q] * s + ox, p.pts[q + 1] * s + oy)
    paint.lineTo(p.pts[q + 2] * s + ox, p.pts[q + 3] * s + oy)
    paint.lineTo(p.pts[q + 4] * s + ox, p.pts[q + 5] * s + oy)
    paint.closePath()
    paint.fillStyle = c
    paint.fill()
    if (!opts.fast) { paint.strokeStyle = c; paint.stroke() }
  }
  if (layer && paint !== ctx) {
    ctx.globalAlpha = opts.ghost ?? 1
    ctx.drawImage(layer, 0, 0)
    ctx.globalAlpha = 1
  }
}

/** Support lines (x0 y0 x1 y1 z each) turned towards the camera the way project() turns triangles: their
 *  ends on screen before scaling, the order to draw them in (far first), and the box they cover. */
export function lineView(lines: Float32Array, { az = -0.6, el = 0.62 }: View = {}) {
  const ca = Math.cos(az), sa = Math.sin(az), ce = Math.cos(el), se = Math.sin(el)
  const n = Math.floor(lines.length / 5)
  const pts = new Float32Array(n * 4)
  const depth = new Float32Array(n)
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
  for (let i = 0; i < n; i++) {
    const z = lines[i * 5 + 4]
    let d = 0
    for (let k = 0; k < 2; k++) {
      const x = lines[i * 5 + k * 2], y = lines[i * 5 + k * 2 + 1]
      const x1 = x * ca - y * sa, y1 = x * sa + y * ca
      const sx = x1, sy = -(y1 * se + z * ce)
      d += y1 * ce - z * se
      pts[i * 4 + k * 2] = sx; pts[i * 4 + k * 2 + 1] = sy
      if (sx < minX) minX = sx; if (sx > maxX) maxX = sx
      if (sy < minY) minY = sy; if (sy > maxY) maxY = sy
    }
    depth[i] = d
  }
  const order = Array.from({ length: n }, (_, i) => i).sort((a, b) => depth[b] - depth[a])
  return { pts, order, box: [minX, minY, maxX, maxY] as const }
}

/** A slice as it prints (design/look/, A with C's layers): every layer's outer wall up to `upTo`, shaded so the
 *  stack reads as the part, and the layer at the cut as its own paths, colored by what each prints. Framed on
 *  the whole stack, so moving the cut never moves the picture. */
export interface LayersPicture { stack: LayerStack; upTo: number; paths: LayerPaths | null; color: string; kindColors: string[] }
export function drawLayers(canvas: HTMLCanvasElement, L: LayersPicture, view: View = {}, pad = 0.1,
  opts: { zoom?: number; shift?: number; fast?: boolean; plateColor?: string; gridColor?: string } = {}): void {
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  const W = canvas.width, H = canvas.height
  ctx.clearRect(0, 0, W, H)
  const w = L.stack.walls, n = Math.floor(w.length / 5)
  if (!n) return
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
  for (let i = 0; i < n; i++) for (const k of [0, 2]) {
    const x = w[i * 5 + k], y = w[i * 5 + k + 1]
    if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y
  }
  const m = Math.max(x1 - x0, y1 - y0) * 0.2
  const plate = new Float32Array([x0 - m, y0 - m, x1 + m, y0 - m, 0, x1 + m, y0 - m, x1 + m, y1 + m, 0, x1 + m, y1 + m, x0 - m, y1 + m, 0,
    x0 - m, y1 + m, x0 - m, y0 - m, 0])
  const pv = lineView(plate, view), sv = lineView(w, view)
  const bx0 = Math.min(pv.box[0], sv.box[0]), by0 = Math.min(pv.box[1], sv.box[1]), bx1 = Math.max(pv.box[2], sv.box[2]), by1 = Math.max(pv.box[3], sv.box[3])
  const shift = opts.shift ?? 0
  const s = Math.min(((W - 2 * Math.abs(shift)) * (1 - 2 * pad)) / (bx1 - bx0 || 1), (H * (1 - 2 * pad)) / (by1 - by0 || 1)) * (opts.zoom ?? 1)
  const ox = (W - (bx1 - bx0) * s) / 2 - bx0 * s + shift, oy = (H - (by1 - by0) * s) / 2 - by0 * s
  // the plate, flat and quiet, with a grid every 10 mm
  const ca = Math.cos(view.az ?? -0.6), sa = Math.sin(view.az ?? -0.6), ce = Math.cos(view.el ?? 0.62), se = Math.sin(view.el ?? 0.62)
  const at = (x: number, y: number, z = 0) => [(x * ca - y * sa) * s + ox, -((x * sa + y * ca) * se + z * ce) * s + oy]
  const corners = [at(x0 - m, y0 - m), at(x1 + m, y0 - m), at(x1 + m, y1 + m), at(x0 - m, y1 + m)]
  ctx.beginPath(); corners.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.closePath()
  ctx.fillStyle = opts.plateColor ?? 'rgba(127,127,127,0.18)'; ctx.fill()
  ctx.save(); ctx.clip()
  ctx.strokeStyle = opts.gridColor ?? 'rgba(127,127,127,0.22)'; ctx.lineWidth = Math.max(1, W / 600)
  const seg = (a: number[], b: number[]) => { ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke() }
  for (let g = Math.ceil((x0 - m) / 10) * 10; g <= x1 + m; g += 10) seg(at(g, y0 - m), at(g, y1 + m))
  for (let g = Math.ceil((y0 - m) / 10) * 10; g <= y1 + m; g += 10) seg(at(x0 - m, g), at(x1 + m, g))
  ctx.restore()
  // the walls below the cut, far first; a wall facing the light is lighter, so the stack has a shape
  const [r, g, b] = rgb(L.color)
  const shades = Array.from({ length: 8 }, (_, i) => { const k = 0.45 + 0.55 * (i / 7); return `rgb(${Math.round(r * k)},${Math.round(g * k)},${Math.round(b * k)})` })
  ctx.lineCap = 'round'
  ctx.lineWidth = Math.max(1, L.stack.width * s)
  const below = L.paths?.n === L.upTo ? L.upTo - 1 : L.upTo
  const step = opts.fast && n > 20000 ? 2 : 1
  for (let j = 0; j < sv.order.length; j += step) {
    const i = sv.order[j]
    if (L.stack.layer[i] > below) continue
    const dx = w[i * 5 + 2] - w[i * 5], dy = w[i * 5 + 3] - w[i * 5 + 1], len = Math.hypot(dx, dy) || 1
    const lit = Math.abs((dy * -0.53 - dx * -0.85) / len)
    ctx.strokeStyle = shades[Math.min(7, Math.round(lit * 7))]
    ctx.beginPath()
    ctx.moveTo(sv.pts[i * 4] * s + ox, sv.pts[i * 4 + 1] * s + oy)
    ctx.lineTo(sv.pts[i * 4 + 2] * s + ox, sv.pts[i * 4 + 3] * s + oy)
    ctx.stroke()
  }
  // the layer at the cut, as the slicer will print it
  if (L.paths && L.paths.n === L.upTo && L.paths.lines.length) {
    const cv = lineView(L.paths.lines, view)
    ctx.lineWidth = Math.max(1, 0.45 * s)
    for (const i of cv.order) {
      ctx.strokeStyle = L.kindColors[L.paths.kinds[i]] ?? L.kindColors[L.kindColors.length - 1]
      ctx.beginPath()
      ctx.moveTo(cv.pts[i * 4] * s + ox, cv.pts[i * 4 + 1] * s + oy)
      ctx.lineTo(cv.pts[i * 4 + 2] * s + ox, cv.pts[i * 4 + 3] * s + oy)
      ctx.stroke()
    }
  }
}

/** The part's triangles with the supports' ends added as flat ones, so the plate drawn under them reaches
 *  a tree that stands out past the part. */
function withLines(tris: Float32Array, sup?: SupportLines | null): Float32Array {
  if (!sup?.lines.length) return tris
  const l = sup.lines, n = Math.floor(l.length / 5)
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
  for (let i = 0; i < n; i++) for (const k of [0, 2]) {
    const x = l[i * 5 + k], y = l[i * 5 + k + 1]
    if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y
  }
  let z = Infinity
  for (let i = 2; i < tris.length; i += 3) z = Math.min(z, tris[i])
  return concat(tris, new Float32Array([x0, y0, z, x1, y0, z, x1, y1, z]))
}

/** A square PNG of the model for the G-code, so the Print tab and Now can show it. Base64, no prefix. */
export function thumbnail(tris: Float32Array, color: string, size = 300): string | null {
  if (!tris.length || typeof document === 'undefined') return null
  const c = document.createElement('canvas')
  c.width = c.height = size
  draw(c, tris, color, {}, 0.08)
  return c.toDataURL('image/png').split(',')[1] ?? null
}

/** "#2563EB" → [37, 99, 235]. Very dark filament is lifted a little so its shape still reads. */
export function rgb(hex: string): [number, number, number] {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim())
  const n = m ? parseInt(m[1], 16) : 0x8a8d91
  const c: [number, number, number] = [(n >> 16) & 255, (n >> 8) & 255, n & 255]
  const lum = 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
  return lum < 50 ? (c.map(v => v + (50 - lum)) as [number, number, number]) : c
}

function concat(a: Float32Array, b: Float32Array): Float32Array {
  const out = new Float32Array(a.length + b.length)
  out.set(a); out.set(b, a.length)
  return out
}

const sub = (a: number[], b: number[]) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
const cross = (a: number[], b: number[]) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
function norm(v: number[]): number[] {
  const l = Math.hypot(v[0], v[1], v[2]) || 1
  return [v[0] / l, v[1] / l, v[2] / l]
}
