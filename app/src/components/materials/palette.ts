// What a person picks from when the printer can't read a spool: SpoolSheet and the one-spool page.

/** Same list, same order as MATERIALS in elyir_bench_intent.py (the intent layer refuses others). */
export const MATERIALS = ['PLA', 'PETG', 'ABS', 'ASA', 'TPU', 'PA', 'PC']

/** Colours filament is commonly sold in. Close enough is fine: matching allows some distance. */
export const COLORS = [
  { name: 'White', hex: '#F4F4F2' }, { name: 'Black', hex: '#1C1C1E' }, { name: 'Gray', hex: '#8A8D91' },
  { name: 'Silver', hex: '#C4C7CC' }, { name: 'Red', hex: '#D32F2F' }, { name: 'Orange', hex: '#FF8800' },
  { name: 'Yellow', hex: '#F5C542' }, { name: 'Green', hex: '#2E9E4F' }, { name: 'Teal', hex: '#14B8A6' },
  { name: 'Blue', hex: '#2563EB' }, { name: 'Navy', hex: '#1E3A8A' }, { name: 'Purple', hex: '#7C3AED' },
  { name: 'Pink', hex: '#EC4899' }, { name: 'Brown', hex: '#8B5A2B' }, { name: 'Beige', hex: '#E3D3B0' },
]

function rgb(hex: string): number[] {
  return [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16))
}

/** The palette colour a spool's colour is closest to, so its swatch shows as picked. */
export function nearestColor(hex: string | null | undefined): string | null {
  if (!hex || !/^#[0-9a-f]{6}$/i.test(hex)) return null
  const [r, g, b] = rgb(hex)
  let best: string | null = null
  let bestD = 70   // the intent layer's "same colour" distance
  for (const c of COLORS) {
    const [r2, g2, b2] = rgb(c.hex)
    const d = Math.hypot(r - r2, g - g2, b - b2)
    if (d < bestD) { best = c.hex; bestD = d }
  }
  return best
}
