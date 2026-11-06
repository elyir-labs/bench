// Pins any side down (design/any-side/, C): the quarter turns, seen from the picture's angle, as the file's direction
// that goes down; a tapped flat face and how the part then stands.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { downOf, faceAt, lit, onto, poseOf, posed, settle, standing, turn, type Pose, type Turn } from '../src/slice/turn.ts'

const turned = (down: number[] | null, t: Turn, az: number) => downOf(turn(poseOf(down), t, az))

// a 10 x 20 x 30 box standing on z = 0, outward-facing triangles
function box(w = 10, d = 20, h = 30): Float32Array {
  const v = (x: number, y: number, z: number) => [x * w, y * d, z * h]
  const quads = [
    [v(0, 0, 0), v(0, 1, 0), v(1, 1, 0), v(1, 0, 0)], [v(0, 0, 1), v(1, 0, 1), v(1, 1, 1), v(0, 1, 1)],
    [v(0, 0, 0), v(1, 0, 0), v(1, 0, 1), v(0, 0, 1)], [v(0, 1, 0), v(0, 1, 1), v(1, 1, 1), v(1, 1, 0)],
    [v(0, 0, 0), v(0, 0, 1), v(0, 1, 1), v(0, 1, 0)], [v(1, 0, 0), v(1, 1, 0), v(1, 1, 1), v(1, 0, 1)],
  ]
  return new Float32Array(quads.flatMap(([a, b, c, e]) => [...a, ...b, ...c, ...a, ...c, ...e]))
}
const near = (a: number[] | null, b: number[] | null) => (a == null || b == null ? a === b : a.every((x, i) => Math.abs(x - b[i]) < 1e-4))
const FRONT = 0          // looking along +y, as the picture would after a turn to az = 0

test('flip over puts the top down, and flipping again is as in the file', () => {
  assert.deepEqual(turned(null, 'flip', -0.6), [0, 0, 1])
  assert.equal(turned([0, 0, 1], 'flip', -0.6), null)
})

test('roll moves the top across the picture, tip moves it towards or away from you', () => {
  assert.ok(near(turned(null, 'rollRight', FRONT), [1, 0, 0]))       // top goes right: the right side lands
  assert.ok(near(turned(null, 'rollLeft', FRONT), [-1, 0, 0]))
  assert.ok(near(turned(null, 'tipForward', FRONT), [0, -1, 0]))     // top comes towards you: the front lands
  assert.ok(near(turned(null, 'tipBack', FRONT), [0, 1, 0]))
})

test('a turn and its opposite, or four the same way, come back to the same pose', () => {
  const same = (a: Pose, b: Pose) => a.every((row, i) => row.every((x, j) => Math.abs(x - b[i][j]) < 1e-9))
  const back: [Turn, Turn][] = [['rollRight', 'rollLeft'], ['tipForward', 'tipBack'], ['flip', 'flip']]
  for (const start of [null, [0, 0, 1], [1, 0, 0], [0, -0.70711, -0.70711]]) {
    for (const az of [-0.6, 0.9, 2.5]) {
      const p0 = poseOf(start)
      for (const [a, b] of back) assert.ok(same(turn(turn(p0, a, az), b, az), p0), `${a} then ${b} from ${start} at ${az}`)
      for (const t of ['rollRight', 'tipBack'] as Turn[]) {
        let p = p0
        const seen = []
        for (let i = 0; i < 4; i++) { p = turn(p, t, az); seen.push(JSON.stringify(downOf(p))) }
        assert.ok(same(p, p0))
        assert.equal(new Set(seen).size, 4, `four ${t} land four different sides`)
      }
    }
  }
})

test('a side tapped in the picture goes down', () => {
  const p = turn(poseOf(null), 'rollRight', FRONT)                        // lying on its right side
  assert.deepEqual(downOf(onto(p, [0, 0, -1])), downOf(p))                 // the side already down: nothing changes
  assert.ok(near(downOf(onto(p, [0, 0, 1])), [-1, 0, 0]))                 // the side facing up now: the left side
})

test('a turn that ends just off a flat facet settles onto it, and one far from any stays put', () => {
  const tilt = (deg: number) => onto(poseOf(null), [0, Math.sin((deg * Math.PI) / 180), -Math.cos((deg * Math.PI) / 180)])
  assert.equal(downOf(settle(tilt(4), box())), null)
  assert.deepEqual(downOf(settle(tilt(30), box())), downOf(tilt(30)))
})

test('a tapped triangle lights its whole flat face', () => {
  const t = box()
  const top = faceAt(t, 2)!
  assert.deepEqual(top.normal.map(x => Math.round(x)), [0, 0, 1])
  assert.deepEqual(top.members, [2, 3])
  const l = lit(t, top.members)
  assert.equal(l.end, 10)
  assert.deepEqual([...l.tris.subarray(90)], [...t.subarray(18, 36)])
})

test('how it stands with a side down', () => {
  assert.deepEqual(standing(box()), { tall: 30, touches: 200 })
  assert.deepEqual(standing(posed(box(), poseOf([1, 0, 0]))), { tall: 10, touches: 600 })
})
