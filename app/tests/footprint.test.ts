// Pins the Brim sheet's pictures (design/brim/, A): what lies on the plate, its outline, its holes, and the
// corners sharp enough for a corner pad, measured from the part's own triangles.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { footprint, roomFor, BRIM_MM } from '../src/slice/footprint.ts'

// boxes as triangles, nine numbers each, the way stl.ts reads them
function boxes(list: [number, number, number, number, number][]): Float32Array {
  const F = [[0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3], [0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6]]
  const out: number[] = []
  for (const [x0, y0, x1, y1, h] of list) {
    const V = [x0, x1].flatMap(x => [y0, y1].flatMap(y => [0, h].map(z => [x, y, z])))
    for (const f of F) for (const i of f) out.push(...V[i])
  }
  return new Float32Array(out)
}

test('an L: one outline, no hole, a pad at each of its five outside corners', () => {
  const f = footprint(boxes([[0, 0, 10, 10, 5], [10, 0, 30, 10, 5], [0, 10, 10, 30, 5]]))!
  assert.equal(f.outer.length, 1)
  assert.equal(f.holes.length, 0)
  assert.deepEqual(f.corners.map(c => c.join(',')).sort(), ['0,0', '0,30', '10,30', '30,0', '30,10'])
  assert.deepEqual(f.box, [0, 0, 30, 30])
  assert.deepEqual(roomFor(f), [-BRIM_MM - 1, -BRIM_MM - 1, 30 + BRIM_MM + 1, 30 + BRIM_MM + 1])
})

test('a frame: the window is a hole, so no brim inside it and no pads on it', () => {
  const cells: [number, number, number, number, number][] = []
  for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) if (i !== 1 || j !== 1) cells.push([i * 10, j * 10, i * 10 + 10, j * 10 + 10, 4])
  const f = footprint(boxes(cells), 2)!                       // at 200%
  assert.equal(f.outer.length, 1)
  assert.equal(f.holes.length, 1)
  assert.deepEqual(f.corners.map(c => c.join(',')).sort(), ['0,0', '0,60', '60,0', '60,60'])
  assert.equal(f.tris.length, 8 * 2 * 6)                      // two triangles per cell, three corners of x, y
})

test('only what touches the plate counts', () => {
  const base = boxes([[0, 0, 10, 10, 5]])
  const shelf = new Float32Array([...base, 0, 0, 3, 40, 0, 3, 0, 40, 3])   // a flat face 3 mm up: not on the plate
  assert.equal(footprint(shelf)!.tris.length, 2 * 6)
  assert.deepEqual(footprint(shelf)!.box, [0, 0, 10, 10])
  assert.equal(footprint(new Float32Array([0, 0, 1, 1, 0, 0, 0, 1, 0])), null)  // edge-on: nothing lies flat
})

test('the words on a part line and on the Brim cards are the ones drawn', async () => {
  const { BRIM_WORDS } = await import('../src/slice/plan.ts')
  assert.deepEqual(['all', 'ears', 'none'].map(k => BRIM_WORDS[k as 'all'].label), ['All round', 'Corners only', 'None'])
  // after "Laid flat · " on a phone's part line: short enough not to be cut off
  for (const k of ['all', 'ears', 'none'] as const) assert.ok(BRIM_WORDS[k].short.length <= 14, BRIM_WORDS[k].short)
})
