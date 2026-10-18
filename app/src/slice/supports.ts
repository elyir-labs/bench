// The supports a slice will print, as lines to draw on each kind's card (design/supports/, A). Pure, so
// tests/slice.test.ts can pin the unpacking.

/** Where a slice's supports go, to draw on its card (design/supports/, A): x0 y0 x1 y1 z per line, in mm on
 *  the bed. width: how wide to draw them (mm), wider when the slicer left layers out to keep it small. */
export interface SupportLines { lines: Float32Array; width: number }

/** The slicer's packing (support_lines in slicer/elyir_bench_slice.py): base64 int16s in tenths of a mm. */
export function decodeLines(d: { count: number; width: number; segs: string }): SupportLines {
  const bin = atob(d.segs)
  const n = Math.min(d.count * 5, Math.floor(bin.length / 2))
  const lines = new Float32Array(n)
  for (let i = 0; i < n; i++) {
    let v = bin.charCodeAt(2 * i) | (bin.charCodeAt(2 * i + 1) << 8)
    if (v > 32767) v -= 65536
    lines[i] = v / 10
  }
  return { lines, width: d.width }
}
