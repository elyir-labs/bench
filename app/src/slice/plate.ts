// The plate in the picture (design/plate/, A): every copy of every part where Orca put it, drawn as one
// model. Orca's arrange decides; until it has (slicing), the copies stand in rows in the middle of the
// bed. Pure functions, so tests/slice.test.ts can pin them.

/** Where Orca put one copy: the centre of its box on the bed in mm, turned anticlockwise in degrees. */
export interface Placed { part: number; x: number; y: number; turn: number }
export interface PlatePart { tris: Float32Array | null; copies: number; scale: number }

/** A part as it prints: scaled, the centre of its box at x = y = 0, resting on z = 0. */
export function centred(tris: Float32Array, scale = 1): Float32Array {
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity, z0 = Infinity
  for (let i = 0; i < tris.length; i += 3) {
    const x = tris[i], y = tris[i + 1], z = tris[i + 2]
    if (x < x0) x0 = x; if (x > x1) x1 = x
    if (y < y0) y0 = y; if (y > y1) y1 = y
    if (z < z0) z0 = z
  }
  const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2
  const out = new Float32Array(tris.length)
  for (let i = 0; i < tris.length; i += 3) {
    out[i] = (tris[i] - cx) * scale
    out[i + 1] = (tris[i + 1] - cy) * scale
    out[i + 2] = (tris[i + 2] - z0) * scale
  }
  return out
}

function footprint(t: Float32Array): [number, number] {
  let x = 0, y = 0
  for (let i = 0; i < t.length; i += 3) { x = Math.max(x, Math.abs(t[i])); y = Math.max(y, Math.abs(t[i + 1])) }
  return [2 * x, 2 * y]
}

/** Before Orca has arranged them: rows across the bed, parts in order, 6 mm apart, the block centred. */
export function provisional(parts: PlatePart[], bed: number[] | null | undefined, gap = 6): Placed[] {
  const W = bed?.[0] ?? 350, H = bed?.[1] ?? 350
  const out: Placed[] = []
  let x = 0, y = 0, rowH = 0, widest = 0
  parts.forEach((p, i) => {
    if (!p.tris) return
    const [w, h] = footprint(centred(p.tris, p.scale))
    for (let c = 0; c < p.copies; c++) {
      if (x > 0 && x + w > W) { y += rowH + gap; x = 0; rowH = 0 }
      out.push({ part: i, x: x + w / 2, y: y + h / 2, turn: 0 })
      x += w + gap; rowH = Math.max(rowH, h); widest = Math.max(widest, x - gap)
    }
  })
  const dx = (W - widest) / 2, dy = (H - (y + rowH)) / 2
  // rows run front to back: the first row at the front (low y)
  return out.map(p => ({ ...p, x: p.x + dx, y: p.y + dy }))
}

/** The plate's colors as runs of triangles, in the order compose() lays them out: each copy of a part gets its
 *  part's runs (counts of triangles and their colors: one run for a part in one color, one per piece for a 3MF
 *  with its own colors). For render's `runs`. */
export function plateRuns(parts: (PlatePart & { runs: { count: number; color: string }[] })[], placed: Placed[]): { end: number; color: string }[] {
  const out: { end: number; color: string }[] = []
  let end = 0
  for (const at of placed) {
    const p = parts[at.part]
    if (!p?.tris) continue
    for (const r of p.runs) {
      end += r.count
      if (out.length && out[out.length - 1].color === r.color) out[out.length - 1].end = end
      else out.push({ end, color: r.color })
    }
  }
  return out
}

/** One set of triangles for the whole plate. Parts that can't be read here (STEP) are left out. */
export function compose(parts: PlatePart[], placed: Placed[]): Float32Array {
  const shapes = parts.map(p => (p.tris ? centred(p.tris, p.scale) : null))
  let n = 0
  for (const at of placed) n += shapes[at.part]?.length ?? 0
  const out = new Float32Array(n)
  let o = 0
  for (const at of placed) {
    const t = shapes[at.part]
    if (!t) continue
    const a = (at.turn * Math.PI) / 180, c = Math.cos(a), s = Math.sin(a)
    for (let i = 0; i < t.length; i += 3) {
      out[o++] = t[i] * c - t[i + 1] * s + at.x
      out[o++] = t[i] * s + t[i + 1] * c + at.y
      out[o++] = t[i + 2]
    }
  }
  return out
}

// ── which parts of a file are on the plate (design/remove-parts/, C) ─────────────────────────────────────────
// A file of several parts (a 3MF) opens on a picker; parts left off wait beside the plate, so "Change" can put
// them back without uploading again. from: the file a part came from; order: its place in that file.

export interface FromFile { key: number; from: string; order: number }

/** The plate after the picker: the parts of `from` that are kept go where that file's first part was (or at the
 *  end), in the file's order; the rest of that file waits off the plate. Other files are untouched. */
export function pickFrom<T extends FromFile>(parts: T[], left: T[], from: string, keep: Set<number>): { parts: T[]; left: T[] } {
  const all = [...parts, ...left].filter(p => p.from === from)
  const chosen = all.filter(p => keep.has(p.key)).sort((a, b) => a.order - b.order)
  const at = parts.findIndex(p => p.from === from)
  const others = parts.filter(p => p.from !== from)
  const before = at < 0 ? others.length : parts.slice(0, at).filter(p => p.from !== from).length
  return {
    parts: [...others.slice(0, before), ...chosen, ...others.slice(before)],
    left: [...left.filter(p => p.from !== from), ...all.filter(p => !keep.has(p.key))],
  }
}

/** Files that brought several parts, with how many of them are on the plate: "4 of 12 from gbp_arm.3mf". */
export function fileCounts(parts: FromFile[], left: FromFile[]): { from: string; on: number; of: number }[] {
  const out = new Map<string, { from: string; on: number; of: number }>()
  for (const [list, on] of [[parts, 1], [left, 0]] as const) {
    for (const p of list) {
      const c = out.get(p.from) ?? { from: p.from, on: 0, of: 0 }
      c.on += on; c.of += 1
      out.set(p.from, c)
    }
  }
  return [...out.values()].filter(c => c.of > 1)
}

/** The first file that brought several parts: it gets the picker. */
export function severalFrom(parts: FromFile[]): string | null {
  const n = new Map<string, number>()
  for (const p of parts) n.set(p.from, (n.get(p.from) ?? 0) + 1)
  return [...n.entries()].find(([, k]) => k > 1)?.[0] ?? null
}
