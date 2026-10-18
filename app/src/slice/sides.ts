// Which side down (design/orientation/, then any side): every side a part can rest on, flattest first, as the slicer
// measured them (`lying.sides`, not sliced). The printer's Print and the Bench Box's model page and plan list them
// alike (components/slice/SidePicks.vue draws each lying that way). Pure, so tests can pin the words.

import type { Lying } from './api.ts'

export const DOWN = [0, 0, -1]
export const sameSide = (a: number[] | null | undefined, b: number[] | null | undefined) =>
  !!a && !!b && a[0] * b[0] + a[1] * b[1] + a[2] * b[2] > 0.996

export function area(mm2: number) { return mm2 >= 100 ? `${Math.round(mm2 / 100)} cm²` : `${Math.round(mm2)} mm²` }
export function supportWords(mm2: number) { return mm2 < 50 ? 'hardly any supports' : `supports under about ${area(mm2)}` }

/** One side to pick: normal null is the file's own bottom. */
export interface SideOption { key: string; normal: number[] | null; title: string; tags: string[]; note: string; on: boolean }

/** Every side it can rest on, `cur` the one down now (null: the file's own bottom). The file's own bottom is one of
 *  them when it touches the plate at all; otherwise it's added, so "as it was drawn" is always there. `own`: the side
 *  the part goes back to by itself, tagged so (the box's "laid flat for you"). */
export function sideOptions(lying: Lying | null | undefined, cur: number[] | null, own?: { normal: number[] | null; tag: string }): SideOption[] {
  if (!lying?.sides?.length) return []
  const isOwn = (n: number[] | null) => !!own && (n == null ? own.normal == null : sameSide(n, own.normal))
  const out: SideOption[] = lying.sides.map((sd, i) => {
    const asFile = sameSide(sd.normal, DOWN)
    const normal = asFile ? null : sd.normal
    return {
      key: sd.normal.join(','), normal,
      title: `${Math.round(sd.size[2])} mm tall`,
      tags: [...(i === 0 ? ['flattest'] : []), ...(asFile ? ['as in the file'] : []), ...(isOwn(normal) ? [own!.tag] : [])],
      note: `Touches ${area(sd.contact)} · ${supportWords(sd.support)}`,
      on: asFile ? cur == null : sameSide(cur, sd.normal),
    }
  })
  if (!out.some((o) => o.normal == null)) {
    out.push({ key: 'file', normal: null, title: 'As in the file', tags: isOwn(null) ? [own!.tag] : [],
      note: lying.down_area < 1 ? 'Standing on an edge or a corner' : `Touches ${area(lying.down_area)}`, on: cur == null })
  }
  return out
}

/** The side that's down, in a line: what touches and how tall it stands. */
export function sideLine(lying: Lying | null | undefined, normal: number[] | null): string {
  if (!lying) return ''
  if (normal == null) return lying.down_area < 1 ? 'Standing on an edge or a corner' : `Touches ${area(lying.down_area)}`
  const s = lying.sides?.find((x) => sameSide(x.normal, normal))
  return s ? `Touches ${area(s.contact)} · ${Math.round(s.size[2])} mm tall` : ''
}
