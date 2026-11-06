// The ring on Now from the file's own layers (design/now-layers/, A): the walls printed so far in the filament's
// color, the layer being printed lit, and a faint ghost of the walls still to come. The same view and shading as
// Look (slice/render.ts drawLayers), framed on the whole stack and its plate so the picture never moves as it grows.
// The geometry is pure, for tests/ring-layers.test.ts; BuildArt.vue does the drawing.

import type { LayerStack } from '../look/layers.ts'
import { lineView, rgb } from '../slice/render.ts'

export interface RingStack {
  stack: LayerStack
  /** each wall projected: x0 y0 x1 y1, far first in `order` */
  pts: Float32Array
  order: number[]
  /** 0..7, lighter for a wall facing the light */
  shade: Uint8Array
  /** where each layer's walls start in the stack (they're in layer order), count + 1 entries */
  starts: Int32Array
  plate: [number, number][]
  box: [number, number, number, number]
}

export function prepare(stack: LayerStack): RingStack | null {
  const w = stack.walls, n = Math.floor(w.length / 5)
  if (!n || !stack.count) return null
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
  for (let i = 0; i < n; i++) for (const k of [0, 2]) {
    const x = w[i * 5 + k], y = w[i * 5 + k + 1]
    if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y
  }
  const m = Math.max(x1 - x0, y1 - y0) * 0.1
  const corners = [[x0 - m, y0 - m], [x1 + m, y0 - m], [x1 + m, y1 + m], [x0 - m, y1 + m]]
  const plateView = lineView(new Float32Array(corners.flatMap(([x, y], i) => [x, y, ...corners[(i + 1) % 4], 0])))
  const v = lineView(w)
  const shade = new Uint8Array(n)
  for (let i = 0; i < n; i++) {
    const dx = w[i * 5 + 2] - w[i * 5], dy = w[i * 5 + 3] - w[i * 5 + 1], len = Math.hypot(dx, dy) || 1
    shade[i] = Math.min(7, Math.round(Math.abs((dy * -0.53 - dx * -0.85) / len) * 7))
  }
  const starts = new Int32Array(stack.count + 1)
  for (let L = 0, i = 0; L <= stack.count; L++) {
    while (i < n && stack.layer[i] < L) i++
    starts[L] = i
  }
  return {
    stack, pts: v.pts, order: v.order, shade, starts,
    plate: corners.map((_, i) => [plateView.pts[i * 4], plateView.pts[i * 4 + 1]]),
    box: [Math.min(v.box[0], plateView.box[0]), Math.min(v.box[1], plateView.box[1]),
      Math.max(v.box[2], plateView.box[2]), Math.max(v.box[3], plateView.box[3])],
  }
}

/** The layer being printed, counted from 0: Klipper's own layer when the file sets it, else how far up it is. */
export function currentLayer(count: number, layer: number | null | undefined, built: number): number {
  const n = layer && layer > 0 ? layer - 1 : Math.round(built * count)
  return Math.max(0, Math.min(count - 1, n))
}

/** The layer to light: the one being printed, or the last one below it the stack kept (a tall print's
 *  stack leaves whole layers out), or -1 when there's none. */
export function litLayer(R: RingStack, n: number): number {
  const i = R.starts[Math.min(n + 1, R.stack.count)] - 1
  return i >= 0 ? R.stack.layer[i] : -1
}

/** Scale and offset that fit the stack and its plate in a W x W face. */
export function fit(R: RingStack, W: number, pad = 0.15) {
  const [bx0, by0, bx1, by1] = R.box, bw = bx1 - bx0 || 1, bh = by1 - by0 || 1
  const s = Math.min((W * (1 - 2 * pad)) / bw, (W * (1 - 2 * pad)) / bh)
  return { s, ox: (W - bw * s) / 2 - bx0 * s, oy: (W - bh * s) / 2 - by0 * s + W * 0.02 }
}

/** Where along layer L's walls the nozzle is drawn, `t` 0..1 of the way round (by length), in projected units. */
export function along(R: RingStack, L: number, t: number): [number, number] | null {
  const a = R.starts[L], b = R.starts[L + 1]
  if (!(b > a)) return null
  const p = R.pts
  let total = 0
  for (let i = a; i < b; i++) total += Math.hypot(p[i * 4 + 2] - p[i * 4], p[i * 4 + 3] - p[i * 4 + 1])
  let left = (((t % 1) + 1) % 1) * total
  for (let i = a; i < b; i++) {
    const len = Math.hypot(p[i * 4 + 2] - p[i * 4], p[i * 4 + 3] - p[i * 4 + 1])
    if (left <= len || i === b - 1) {
      const k = len ? Math.min(1, left / len) : 0
      return [p[i * 4] + (p[i * 4 + 2] - p[i * 4]) * k, p[i * 4 + 1] + (p[i * 4 + 3] - p[i * 4 + 1]) * k]
    }
    left -= len
  }
  return null
}

export interface RingInk { ink: string; accent: string }

/** The part that only changes with the layer: the plate, the ghost above the lit layer, the walls below it. */
export function paintStack(c: HTMLCanvasElement, R: RingStack, lit: number, color: string, ink: RingInk): void {
  const ctx = c.getContext('2d')
  if (!ctx) return
  const W = c.width, { s, ox, oy } = fit(R, W), p = R.pts, layer = R.stack.layer
  ctx.clearRect(0, 0, W, W)
  ctx.globalAlpha = 0.07
  ctx.fillStyle = ink.ink
  ctx.beginPath()
  R.plate.forEach(([x, y], i) => (i ? ctx.lineTo(x * s + ox, y * s + oy) : ctx.moveTo(x * s + ox, y * s + oy)))
  ctx.closePath(); ctx.fill()
  ctx.globalAlpha = 1
  ctx.lineCap = 'round'
  const seg = (g: CanvasRenderingContext2D, i: number) => {
    g.beginPath(); g.moveTo(p[i * 4] * s + ox, p[i * 4 + 1] * s + oy); g.lineTo(p[i * 4 + 2] * s + ox, p[i * 4 + 3] * s + oy); g.stroke()
  }
  // the ghost: drawn solid on its own canvas, then laid on faint, so crossing lines don't add up
  if (R.starts[lit + 1] < R.order.length) {
    const g = document.createElement('canvas'); g.width = g.height = W
    const gc = g.getContext('2d')!
    gc.lineCap = 'round'; gc.strokeStyle = ink.ink; gc.lineWidth = Math.max(1, W / 260)
    for (const i of R.order) if (layer[i] > lit) seg(gc, i)
    ctx.globalAlpha = 0.13; ctx.drawImage(g, 0, 0); ctx.globalAlpha = 1
  }
  const [r, gg, b] = rgb(color)
  const shades = Array.from({ length: 8 }, (_, i) => { const k = 0.45 + 0.55 * (i / 7); return `rgb(${Math.round(r * k)},${Math.round(gg * k)},${Math.round(b * k)})` })
  ctx.lineWidth = Math.max(1, R.stack.width * s)
  for (const i of R.order) {
    if (layer[i] >= lit) continue
    ctx.strokeStyle = shades[R.shade[i]]
    seg(ctx, i)
  }
}

/** On top, every frame: the lit layer, and the nozzle going round it. */
export function paintLayer(ctx: CanvasRenderingContext2D, R: RingStack, lit: number, ink: RingInk, line: string | null, nozzleAt: number | null): void {
  const W = ctx.canvas.width, { s, ox, oy } = fit(R, W), p = R.pts
  if (lit < 0) return
  if (line) {
    ctx.lineCap = 'round'; ctx.strokeStyle = line; ctx.lineWidth = Math.max(1.5, R.stack.width * s * 1.2)
    for (let i = R.starts[lit]; i < R.starts[lit + 1]; i++) {
      ctx.beginPath(); ctx.moveTo(p[i * 4] * s + ox, p[i * 4 + 1] * s + oy); ctx.lineTo(p[i * 4 + 2] * s + ox, p[i * 4 + 3] * s + oy); ctx.stroke()
    }
  }
  const at = nozzleAt == null ? null : along(R, lit, nozzleAt)
  if (!at) return
  const x = at[0] * s + ox, y = at[1] * s + oy, k = W / 200
  ctx.fillStyle = ink.ink
  ctx.beginPath()
  ctx.moveTo(x - 6 * k, y - 15 * k); ctx.lineTo(x + 6 * k, y - 15 * k); ctx.lineTo(x + 6 * k, y - 9 * k)
  ctx.lineTo(x + 2 * k, y - 2 * k); ctx.lineTo(x - 2 * k, y - 2 * k); ctx.lineTo(x - 6 * k, y - 9 * k)
  ctx.closePath(); ctx.fill()
}
