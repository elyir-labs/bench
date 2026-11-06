// npm test  (node --experimental-strip-types --test tests/)
// The ring on Now from the file's own layers (design/now-layers/, A): which layer is lit, where the nozzle goes, and a
// frame that holds still while the print grows.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { along, currentLayer, fit, litLayer, prepare } from '../src/art/ringLayers.ts'
import type { LayerStack } from '../src/look/layers.ts'

/** A 10 mm square wall on every kept layer, 0.2 mm apart. */
function square(count: number, keep = (_: number) => true): LayerStack {
  const walls: number[] = [], layer: number[] = []
  for (let L = 0; L < count; L++) {
    if (!keep(L)) continue
    const z = 0.2 * (L + 1)
    for (const [a, b, c, d] of [[0, 0, 10, 0], [10, 0, 10, 10], [10, 10, 0, 10], [0, 10, 0, 0]]) { walls.push(a, b, c, d, z); layer.push(L) }
  }
  return { count, z: Array.from({ length: count }, (_, L) => 0.2 * (L + 1)), width: 0.45, walls: new Float32Array(walls), layer: new Uint16Array(layer) }
}

test("the lit layer is Klipper's own, counted from 1, or how far up it is when the file doesn't say", () => {
  assert.equal(currentLayer(100, 42, 0.9), 41)
  assert.equal(currentLayer(100, null, 0.5), 50)
  assert.equal(currentLayer(100, 0, 0), 0)
  assert.equal(currentLayer(100, 500, 1), 99)   // a count that disagrees with the file's never runs off the top
})

test('each layer knows where its walls are, and a layer the stack left out lights the one below it', () => {
  const R = prepare(square(6, (L) => L % 2 === 0))!
  assert.deepEqual([...R.starts], [0, 4, 4, 8, 8, 12, 12])
  assert.equal(litLayer(R, 4), 4)
  assert.equal(litLayer(R, 3), 2)
  assert.equal(prepare(square(0)), null)
})

test('the frame is the whole stack and its plate, so it never moves as the print grows', () => {
  const R = prepare(square(20))!
  const a = fit(R, 400), [x0, y0, x1, y1] = R.box
  for (const [x, y] of [[x0, y0], [x1, y1]]) {
    assert.ok(x * a.s + a.ox >= 0 && x * a.s + a.ox <= 400)
    assert.ok(y * a.s + a.oy >= 0 && y * a.s + a.oy <= 400)
  }
})

test('the nozzle goes round the lit layer, higher up the picture on a higher layer', () => {
  const R = prepare(square(20))!
  const low = along(R, 0, 0)!, high = along(R, 19, 0)!
  assert.ok(high[1] < low[1])
  // all the way round comes back to the start
  const end = along(R, 5, 0.999999)!, start = along(R, 5, 0)!
  assert.ok(Math.hypot(end[0] - start[0], end[1] - start[1]) < 0.01)
  assert.equal(along(R, 25, 0), null)
})
