// Helpers for turning slicer metadata into things a person recognises.
// Mirrors the same rules in elyir_bench_intent.py.

export interface JobMeta {
  filament_colors?: string[]
  filament_type?: string
  filament_weights?: number[]
  filament_weight_total?: number
  thumbnails?: { width?: number; height?: number; relative_path?: string }[]
  [k: string]: unknown
}

/** File name to a name: strips slicer suffixes and Orca's "[a]_" plate prefix. */
export function prettyName(filename: string): string {
  let n = filename.split('/').pop() || filename
  n = n.replace(/\.(gcode|gco|g)$/i, '')
  n = n.replace(/^\[[^\]]*\][_ ]*/, '')
  n = n.replace(/_(\d+(\.\d+)?mm|PLA|PETG|ABS|ASA|TPU|NYLON|PC|PA|\d+h\d*m?\d*s?|\d+m\d*s?|\d+s|MK3S?|MK4S?|MINI|XL|X1C?|P1[SP]|A1|VORON)(?=_|$)/gi, '')
  // a plate from Elyir Bench's slicer (design/plate/): "_x25" copies, "_1of2" which plate
  n = n.replace(/_x(\d+)(?=_|$)/g, ' × $1').replace(/_(\d+)of(\d+)(?=_|$)/g, ' (plate $1 of $2)')
  n = n.replace(/[_-]+/g, ' ').trim()
  return n.charAt(0).toUpperCase() + n.slice(1)
}

/** Which extruders the file actually used. Slicers list every filament in the profile. */
export function usedExtruders(meta: JobMeta | undefined | null): number[] {
  const w = meta?.filament_weights
  if (Array.isArray(w) && w.some(x => typeof x === 'number' && x > 0)) return w.map((x, i) => (x > 0 ? i : -1)).filter(i => i >= 0)
  return (meta?.filament_colors ?? []).map((_, i) => i)
}

export function usedColors(meta: JobMeta | undefined | null): string[] {
  const colors = meta?.filament_colors ?? []
  return usedExtruders(meta).map(i => colors[i]).filter((c): c is string => !!c).map(c => c.toUpperCase())
}

export function humanDuration(seconds: number | null | undefined): string {
  if (seconds == null) return ''
  const m = Math.round(seconds / 60)
  if (m < 1) return 'under a minute'
  if (m < 60) return `${m} min`
  const h = Math.floor(m / 60), r = m % 60
  return r ? `${h} h ${r} m` : `${h} h`
}
