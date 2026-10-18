// The picture in the ring when there's no camera (design/now-illustrated/, A). Pure geometry,
// so it can be tested: StepArt.vue draws getting ready, BuildArt.vue the print going up.
// Everything here turns one of the printer's own numbers into a place on a 200 x 200 face.

import type { IntentArt } from '../intent/types'

/** The bed, drawn at an angle: x and y from -1 to 1 (y -1 at the back), z in bed widths up. */
export function iso(x: number, y: number, z = 0): [number, number] {
  return [100 + (x - y) * 40, 128 + (x + y) * 23 - z * 58]
}

/** Klipper's 0..1 across the axes (y 0 at the front) to the drawing's -1..1 (y -1 at the back). */
export function bedPoint(nx: number, ny: number): [number, number] {
  return [nx * 2 - 1, 1 - ny * 2]
}

/** Where the nozzle tip is drawn for a head at [x, y, z mm]. The head's height above the bed is
 *  squeezed: 0 to 40 mm reads as touching to well clear. */
export function headAt(head: [number, number, number]): [number, number] {
  const [x, y] = bedPoint(head[0], head[1])
  return iso(x, y, Math.min(1, Math.max(0, head[2]) / 40) * 0.6 + 0.05)
}

/** How warm to draw something heading for `target`: 0 at room temperature, 1 there. */
export function warmth(t: number, target: number, room = 24): number {
  if (!target || target <= room) return 0
  return Math.min(1, Math.max(0, (t - room) / (target - room)))
}

/** The gantry's tilt in px either side, from the last levelling pass. No pass yet: clearly
 *  tilted. Within tolerance: flat. Between, it shrinks with the range, on a log scale, since
 *  QGL goes from tenths of a millimetre to thousandths in two or three passes. */
export function tilt(level: IntentArt['level']): number {
  if (!level) return 9
  const r = level.range / Math.max(level.tolerance, 1e-4)
  if (r <= 1) return 0
  return Math.min(11, 2 + Math.log10(r) * 4.5)
}

export interface MeshCell { poly: [number, number][]; lit: boolean; center: [number, number] }

/** The bed as n x n cells; a cell is lit when the head has been over it (bit j*n+i, j from the front). */
export function meshCells(mesh: NonNullable<IntentArt['mesh']>): MeshCell[] {
  const { n, seen } = mesh, size = 2 / n, out: MeshCell[] = []
  for (let j = 0; j < n; j++) {
    for (let i = 0; i < n; i++) {
      const x0 = -1 + i * size, y1 = 1 - j * size, y0 = y1 - size
      out.push({
        poly: [iso(x0, y0), iso(x0 + size, y0), iso(x0 + size, y1), iso(x0, y1)],
        lit: !!(seen & (1 << (j * n + i))),   // n is 5, so 25 bits: plain number bit ops are safe
        center: iso(x0 + size / 2, y0 + size / 2),
      })
    }
  }
  return out
}

/** Where the object starts and ends in its picture, as fractions of the picture's height, from
 *  whether each row has anything solid in it. Slicer pictures are mostly empty around the object. */
export function objectBounds(rowsWithPixels: boolean[]): { top: number; bot: number } {
  const first = rowsWithPixels.indexOf(true), last = rowsWithPixels.lastIndexOf(true)
  if (first < 0) return { top: 0, bot: 1 }
  return { top: first / rowsWithPixels.length, bot: (last + 1) / rowsWithPixels.length }
}

/** The line the object is built up to: from the bottom of the object to its top as `built` goes 0 to 1. */
export function cutAt(bounds: { top: number; bot: number }, built: number): number {
  return bounds.bot - (bounds.bot - bounds.top) * Math.min(1, Math.max(0, built))
}

export const pts = (a: [number, number][]) => a.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
