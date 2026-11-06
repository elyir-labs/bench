// Pins where supports go (design/supports-where/, A "tap the places", picked 2 November 2026): the faces that point
// down found as places, switching one on or off, what goes to the slicer for each "where", and the words.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { changed, fromRuns, HERE, isOn, marksToSend, NOT_HERE, placeName, places, placeSize, placeWho, strayArea, turned } from '../src/slice/places.ts'

type V = [number, number, number]
/** A box as 12 triangles, facing out: bottom 0-1, top 2-3, then the four sides. */
function box([x0, y0, z0]: V, [x1, y1, z1]: V): number[] {
  const v = (i: number): V => [i & 4 ? x1 : x0, i & 2 ? y1 : y0, i & 1 ? z1 : z0]
  const faces = [[0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3], [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6], [0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5]]
  return faces.flatMap(f => f.flatMap(v))
}
/** A 20 x 10 mm face leaning 40° from flat, facing down, its low edge 10 mm up: the ear on the board's bracket. */
function ear(): number[] {
  const dh = 10 * Math.tan((40 * Math.PI) / 180)
  const a: V = [50, 0, 10], b: V = [50, 10, 10 + dh], c: V = [70, 10, 10 + dh], d: V = [70, 0, 10]
  return [...a, ...b, ...c, ...a, ...c, ...d]
}
const tris = (...parts: number[][]) => new Float32Array(parts.flat())
// a shelf bracket: a base and a back wall on the plate, a shelf that sticks out 15 mm past the base
const BRACKET = tris(box([0, 0, 0], [40, 30, 3]), box([0, 25, 0], [40, 30, 22]), box([0, -15, 22], [40, 30, 25]), ear())
const N = BRACKET.length / 9

test('a cube on the plate has nowhere that points down', () => {
  assert.deepEqual(places(tris(box([0, 0, 0], [20, 20, 20]))), [])
})

test('the shelf is a flat place Orca holds up; the leaning ear is one it leaves', () => {
  const [shelf, leaning] = places(BRACKET)
  assert.deepEqual(shelf.tris.sort(), [24, 25])
  assert.equal(Math.round(shelf.area), 1800)
  assert.deepEqual([shelf.auto, Math.round(shelf.lean), shelf.z, shelf.size], [true, 0, 22, [40, 45]])
  assert.deepEqual(leaning.tris.sort(), [36, 37])
  assert.deepEqual([leaning.auto, Math.round(leaning.lean), leaning.z], [false, 40, 10])
  assert.equal(places(BRACKET, 2)[0].area, 7200)                              // at the printed size
  assert.equal(places(BRACKET, 1, 40)[1].auto, true)                          // a Kobra's profile supports up to 40°
  assert.equal(places(BRACKET, 1, 30, 2000).length, 0)                        // too small to list
})

test('a place switched keeps a mark only where it differs from Orca', () => {
  const [shelf, leaning] = places(BRACKET)
  assert.equal(isOn(shelf, null), true)
  assert.equal(isOn(leaning, null), false)
  const off = turned(shelf, null, N, false)
  assert.deepEqual([off[24], off[25]], [NOT_HERE, NOT_HERE])
  assert.equal(isOn(shelf, off), false)
  const both = turned(leaning, off, N, true)
  assert.deepEqual([both[36], both[37]], [HERE, HERE])
  assert.deepEqual(changed([shelf, leaning], both), { added: 1, off: 1 })
  const back = turned(shelf, both, N, true)
  assert.deepEqual([back[24], back[25]], [0, 0])
  assert.deepEqual(changed([shelf, leaning], back), { added: 1, off: 0 })
})

test('"Where it\'s needed" sends the marks; "Only where I say" sends every place that\'s on', () => {
  const found = places(BRACKET)
  assert.equal(marksToSend(null, found, 'needed', N), null)
  const marks = turned(found[1], null, N, true)
  assert.equal(marksToSend(marks, found, 'needed', N), marks)
  const only = marksToSend(marks, found, 'only', N)!
  assert.deepEqual([only[24], only[25], only[36], only[37]], [HERE, HERE, HERE, HERE])
  assert.equal(only.filter(v => v).length, 4)
  const none = turned(found[0], null, N, false)
  assert.equal(marksToSend(none, found, 'only', N), null)                    // the shelf off and nothing added: no supports
})

test('marks come from the slicer as runs, and are dropped when they no longer fit the part', () => {
  assert.deepEqual([...fromRuns([0, 2, 1, 1, 2, 1], 4)!], [0, 0, 1, 2])
  assert.equal(fromRuns([0, 2, 1, 1], 4), null)
  assert.equal(fromRuns([0, 5], 4), null)
  assert.equal(fromRuns(null, 4), null)
})

test('a mark left where nothing points down any more is noticed', () => {
  const found = places(BRACKET)
  const marks = new Uint8Array(N)
  marks[26] = HERE                                                            // the shelf's top: half of 40 x 45
  assert.equal(strayArea(BRACKET, marks, found), 900)
  marks[26] = 0; marks[24] = NOT_HERE
  assert.equal(strayArea(BRACKET, marks, found), 0)
})

test('the words for a place', () => {
  const [shelf, leaning] = places(BRACKET)
  assert.equal(placeName(shelf), 'Flat underside')
  assert.equal(placeName(leaning), 'Leans 40°')
  assert.equal(placeSize(shelf), '40 × 45 mm · 22 mm up')
  assert.equal(placeWho(shelf, true), 'Orca holds it up')
  assert.equal(placeWho(shelf, false), 'You took it off')
  assert.equal(placeWho(leaning, true), 'You added it')
})
