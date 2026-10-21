// Pins painting and a change at a height (design/paint-and-height/, picked 21 October 2026: height C with A's line,
// painting A): the flat top Bench spots, colors by height, a tap filling up to an edge or a spot, the paint sent to
// the slicer, the layer a height lands on, and the triangle under a tap.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { drawRuns, fillFrom, flatTop, heightColors, neighbours, paintUses, snapToLayer, spotFrom, toRuns } from '../src/slice/paint.ts'
import { pick } from '../src/slice/render.ts'

type V = [number, number, number]
/** A box as 12 triangles, facing out: bottom 0-1, top 2-3, then the four sides. */
function box([x0, y0, z0]: V, [x1, y1, z1]: V): number[] {
  const v = (i: number): V => [i & 4 ? x1 : x0, i & 2 ? y1 : y0, i & 1 ? z1 : z0]
  const faces = [[0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3], [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6], [0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5]]
  return faces.flatMap(f => f.flatMap(v))
}
const tris = (...boxes: number[][]) => new Float32Array(boxes.flat())
// a sign: a 100 x 36 x 3.2 mm plate with two raised letters to 5 mm
const SIGN = tris(box([0, 0, 0], [100, 36, 3.2]), box([15, 10, 3.2], [40, 26, 5]), box([55, 10, 3.2], [85, 26, 5]))

test('Bench spots the letters on top of a sign, and the base under a figure', () => {
  assert.deepEqual(flatTop(SIGN), { z: 3.2, raised: true })
  assert.deepEqual(flatTop(SIGN, 2), { z: 6.4, raised: true })                     // at its printed size
  const figure = tris(box([0, 0, 0], [30, 30, 2]), box([10, 10, 2], [20, 20, 40]))   // a tall thing on a thin base
  assert.deepEqual(flatTop(figure), { z: 2, raised: false })
  assert.equal(flatTop(tris(box([0, 0, 0], [20, 20, 20]))), null)                 // a cube: nothing on top of anything
  const pin = tris(box([0, 0, 0], [40, 40, 3]), box([18, 18, 3], [22, 22, 40]))   // a pin on a plate
  assert.equal(flatTop(pin)?.z, 3)
  const ledge = tris(box([0, 0, 0], [40, 40, 20]), box([0, 0, 20], [40, 39, 30]))  // two bodies: a 1 mm ledge is left, too small
  assert.equal(flatTop(ledge), null)
})

test('from a height up, the triangles take the new color; a flat top at the height keeps the color below', () => {
  const c = heightColors(SIGN, [{ z: 3.2, spool: 1 }], 1, 0)
  assert.deepEqual([...c.slice(0, 12)], Array(12).fill(1))       // the plate, its top included
  const letters = [...c.slice(12)].filter((_, i) => i % 12 >= 2)  // the letters but their hidden bottoms
  assert.deepEqual([...new Set(letters)], [2])
  assert.deepEqual([c[12], c[13]], [1, 1])                         // a letter's bottom lies on the plate's top
  assert.deepEqual([...heightColors(SIGN, [], 1, 2)].slice(0, 2), [3, 3])
  // white, black, then white again from 4.4 mm: the letters' tops are white
  const back = heightColors(SIGN, [{ z: 4.4, spool: 0 }, { z: 3.2, spool: 1 }], 1, 0)
  assert.equal(back[12 + 2], 1)                                   // a letter's top (its third face)
})

test('a tap fills up to the edge: a lid is one face, a spot is a few triangles', () => {
  const lidBox = tris(box([0, 0, 0], [60, 40, 30]))
  const near = neighbours(lidBox)
  assert.ok([...near].every(n => n >= 0), 'a closed box: every edge has a neighbour')
  assert.deepEqual(fillFrom(lidBox, near, 2).sort(), [2, 3])     // the top's two triangles, not the sides
  const smooth = fillFrom(lidBox, near, 2, 100)
  assert.equal(smooth.length, 12)                                 // with no edge sharp enough, it spreads all round
  assert.deepEqual(spotFrom(SIGN, neighbours(SIGN), 2, 1), [2])   // a spot on a big face: the triangle tapped
})

test('paint goes to the slicer as runs, and draws as runs of colors', () => {
  const s = new Uint8Array([0, 0, 2, 2, 2, 0, 1])
  assert.deepEqual(toRuns(s), [0, 2, 2, 3, 0, 1, 1, 1])
  assert.equal(toRuns(new Uint8Array(4)), null)
  assert.deepEqual([...paintUses(s)].sort(), [0, 1])
  assert.deepEqual(drawRuns(s, k => ['own', 'a', 'b'][k]), [{ end: 2, color: 'own' }, { end: 5, color: 'b' }, { end: 6, color: 'own' }, { end: 7, color: 'a' }])
})

test('a height lands on the layer that starts there, counted as people count', () => {
  assert.deepEqual(snapToLayer(3.2, 5, 0.2, 0.2), { z: 3.2, n: 17, of: 25 })
  assert.deepEqual(snapToLayer(3.25, 5, 0.2, 0.2), { z: 3.4, n: 18, of: 25 })
  assert.deepEqual(snapToLayer(3.2, 5, 0.2, 0.28), { z: 3.28, n: 13, of: 19 })
})

test('a tap finds the nearest triangle under it', () => {
  const cube = tris(box([0, 0, 0], [20, 20, 20]))
  const W = 400, H = 400
  const top = pick(cube, W, H, 200, 140)                           // above the middle: the lid, seen from above
  assert.ok(top === 2 || top === 3, `got ${top}`)
  assert.equal(pick(cube, W, H, 5, 5), -1)                          // the corner of the picture: nothing there
})
