// npm test  (node --experimental-strip-types --test tests/)
// The picture in the ring without a camera (design/now-illustrated/, A): each drawing is the
// printer's own number put in a place. These pin the mapping.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { bedPoint, cutAt, headAt, iso, meshCells, objectBounds, tilt, warmth } from '../src/art/ringArt.ts'

test("Klipper's front-left corner is the drawing's front-left corner", () => {
  assert.deepEqual(bedPoint(0, 0), [-1, 1])
  assert.deepEqual(bedPoint(1, 1), [1, -1])
  // front-left sits left of and below the back-right in the picture
  const fl = iso(...bedPoint(0, 0)), br = iso(...bedPoint(1, 1))
  assert.ok(fl[0] < 100 && br[0] > 100 || fl[1] > br[1])
})

test('a head higher up is drawn higher up', () => {
  assert.ok(headAt([0.5, 0.5, 30])[1] < headAt([0.5, 0.5, 2])[1])
})

test('the gantry flattens as the levelling range comes into tolerance', () => {
  assert.equal(tilt(null), 9)
  const big = tilt({ range: 0.41, tolerance: 0.0075 }), mid = tilt({ range: 0.056, tolerance: 0.0075 })
  assert.ok(big > mid && mid > 0)
  assert.equal(tilt({ range: 0.004, tolerance: 0.0075 }), 0)
  assert.ok(tilt({ range: 50, tolerance: 0.0075 }) <= 11)
})

test('mesh cells light where the printer says the head has been, counted from the front', () => {
  const cells = meshCells({ n: 5, seen: 0b11111 })
  assert.equal(cells.length, 25)
  assert.deepEqual(cells.map((c) => c.lit).slice(0, 6), [true, true, true, true, true, false])
  // the first row is the front: drawn lower in the picture than the last row
  assert.ok(cells[0].center[1] > cells[20].center[1])
})

test('warmth runs from the room to the target and stops there', () => {
  assert.equal(warmth(24, 60), 0)
  assert.equal(warmth(42, 60), 0.5)
  assert.equal(warmth(70, 60), 1)
  assert.equal(warmth(50, 0), 0)
})

test('the object is found in its picture and cut at the layer it is on', () => {
  const rows = [false, false, true, true, true, true, true, true, false, false]
  const b = objectBounds(rows)
  assert.deepEqual(b, { top: 0.2, bot: 0.8 })
  assert.equal(cutAt(b, 0), 0.8)
  assert.ok(Math.abs(cutAt(b, 1) - 0.2) < 1e-9)
  assert.ok(Math.abs(cutAt(b, 0.5) - 0.5) < 1e-9)
  assert.deepEqual(objectBounds([false, false]), { top: 0, bot: 1 })
})
