// Layers (design/look/, A with C's layers): a slice as the slicer reads it back (layer_index, layer_paths in
// slicer/elyir_bench_slice.py), unpacked to draw. Pure, so tests/look.test.ts can pin it.

export const WALL = 0, INNER = 1, INFILL = 2, SUPPORT = 3, OTHER = 4
export const KIND_NAMES = ['Outer wall', 'Inner wall', 'Infill', 'Support'] as const

/** Every layer's outer wall up to the top: x0 y0 x1 y1 z per segment, each segment's layer, the layers' heights. */
export interface LayerStack { count: number; z: number[]; width: number; walls: Float32Array; layer: Uint16Array }
/** One layer's paths: x0 y0 x1 y1 z per segment, and what each prints (WALL...OTHER). */
export interface LayerPaths { n: number; lines: Float32Array; kinds: Uint8Array }

function bytes(b64: string): Uint8Array {
  const bin = atob(b64)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}
function tenths(b64: string, n: number): Float32Array {
  const b = bytes(b64), v = new DataView(b.buffer)
  const out = new Float32Array(Math.min(n, Math.floor(b.length / 2)))
  for (let i = 0; i < out.length; i++) out[i] = v.getInt16(i * 2, true) / 10
  return out
}

export function stackFrom(d: { count: number; z: number[]; width: number; walls: { count: number; segs: string; layer: string } }): LayerStack {
  const b = bytes(d.walls.layer), v = new DataView(b.buffer)
  const layer = new Uint16Array(Math.min(d.walls.count, Math.floor(b.length / 2)))
  for (let i = 0; i < layer.length; i++) layer[i] = v.getUint16(i * 2, true)
  return { count: d.count, z: d.z, width: d.width, walls: tenths(d.walls.segs, d.walls.count * 5), layer }
}

export function pathsFrom(n: number, d: { count: number; segs: string; kinds: string }): LayerPaths {
  return { n, lines: tenths(d.segs, d.count * 5), kinds: bytes(d.kinds).slice(0, d.count) }
}

/** "Layer 42 of 110 · 8.4 mm", counted from 1 as people count. */
export function layerWords(s: LayerStack, n: number): string {
  const z = s.z[n] ?? 0
  return `Layer ${n + 1} of ${s.count} · ${z < 10 ? Math.round(z * 100) / 100 : Math.round(z * 10) / 10} mm`
}

/** Which kinds a layer has, for the legend: only those it prints. */
export function kindsIn(p: LayerPaths | null): number[] {
  if (!p) return []
  const seen = new Set<number>()
  for (const k of p.kinds) if (k < OTHER) seen.add(k)
  return [...seen].sort()
}
