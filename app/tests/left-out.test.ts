// Pins the picture of what the slicer left out (design/thin-walls/): the part cut at the slicer's heights, the
// printed triangles first in the part's color, the rest in pale stripes, nothing lost or turned inside out.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { LEFT_OUT_STRIPES, leftOutRuns } from '../src/slice/plate.ts'

function box(w = 10, d = 20, h = 30): Float32Array {
  const v = (x: number, y: number, z: number) => [x * w, y * d, z * h]
  const quads = [
    [v(0, 0, 0), v(0, 1, 0), v(1, 1, 0), v(1, 0, 0)], [v(0, 0, 1), v(1, 0, 1), v(1, 1, 1), v(0, 1, 1)],
    [v(0, 0, 0), v(1, 0, 0), v(1, 0, 1), v(0, 0, 1)], [v(0, 1, 0), v(0, 1, 1), v(1, 1, 1), v(1, 1, 0)],
    [v(0, 0, 0), v(0, 0, 1), v(0, 1, 1), v(0, 1, 0)], [v(1, 0, 0), v(1, 1, 0), v(1, 1, 1), v(1, 0, 1)],
  ]
  return new Float32Array(quads.flatMap(([a, b, c, e]) => [...a, ...b, ...c, ...a, ...c, ...e]))
}

// outward area along +x, +y, +z: the same for the cut mesh as the whole one only when every piece keeps its winding
function normals(t: Float32Array): number[] {
  const s = [0, 0, 0]
  for (let i = 0; i < t.length; i += 9) {
    const u = [t[i + 3] - t[i], t[i + 4] - t[i + 1], t[i + 5] - t[i + 2]], w = [t[i + 6] - t[i], t[i + 7] - t[i + 1], t[i + 8] - t[i + 2]]
    const n = [u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0]]
    for (const k of [0, 1, 2]) s[k] += Math.max(n[k], 0)
  }
  return s
}
const zs = (t: Float32Array, from: number, to: number) => { const o = []; for (let i = from * 9 + 2; i < to * 9; i += 3) o.push(t[i]); return o }

test('the top that won\'t print is cut off and drawn in stripes', () => {
  const b = box()
  const { tris, runs } = leftOutRuns(b, 1, { bottom: 0, top: 9, all: false }, '#2563EB')
  assert.equal(runs[0].color, '#2563EB')
  assert.deepEqual(runs.slice(1).map(r => r.color), LEFT_OUT_STRIPES)
  assert.ok(Math.max(...zs(tris, 0, runs[0].count)) <= 21 + 1e-4)
  assert.ok(Math.min(...zs(tris, runs[0].count, tris.length / 9)) >= 21 - 1e-4)
  assert.deepEqual(normals(tris).map(Math.round), normals(b).map(Math.round))
})

test('a missing bottom, a whole part, and the size it prints at', () => {
  const b = box()
  const bottom = leftOutRuns(b, 1, { bottom: 3, top: 0, all: false }, '#111111')
  assert.ok(Math.min(...zs(bottom.tris, 0, bottom.runs[0].count)) >= 3 - 1e-4)
  const half = leftOutRuns(b, 0.5, { bottom: 0, top: 5, all: false }, '#111111')
  assert.ok(Math.max(...zs(half.tris, 0, half.runs[0].count)) <= 20 + 1e-4)     // 5 mm on the plate is 10 in the file
  const all = leftOutRuns(b, 1, { bottom: 0, top: 30, all: true }, '#111111')
  assert.ok(all.runs.every(r => LEFT_OUT_STRIPES.includes(r.color)))
})
