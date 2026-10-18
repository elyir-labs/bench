// Pins which side down on the Bench Box (the printer's own design/orientation/, on the box 11 October 2026): the Lying
// row's words, each part's sides with its own tagged, a tap shown at once as the box keeps it, the setup key, and the
// picture with each part on its side.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { canPickSide, laidPicture, ownTag, partName, partOptions, partWords, pickOf, sideRow, sidesKey, withSide, type SidePart, type SidesView } from '../src/bench-app/sides.ts'
import { setupKey, DEFAULT_HOW } from '../src/bench-app/how.ts'
import { sideOptions } from '../src/slice/sides.ts'
import type { Lying } from '../src/slice/api.ts'

const UP = [0, 0, 1], DOWN = [0, 0, -1], EAST = [1, 0, 0], NORTH = [0, 1, 0]
// a 30 x 3 x 20 mount, standing on its edge: its flattest side faces north
const MOUNT: Lying = {
  down_area: 90, flat_area: 600, flat_normal: NORTH, flat_better: true, tilt: 90, size_flat: [30, 20, 3],
  sides: [
    { normal: NORTH, contact: 600, size: [30, 20, 3], support: 0 },
    { normal: [0, -1, 0], contact: 600, size: [30, 20, 3], support: 0 },
    { normal: DOWN, contact: 90, size: [30, 3, 20], support: 0 },
    { normal: UP, contact: 90, size: [30, 3, 20], support: 0 },
    { normal: EAST, contact: 60, size: [3, 20, 30], support: 120 },
  ],
}
const part = (p: Partial<SidePart> = {}): SidePart => ({
  n: 0, name: 'mount.stl', lying: MOUNT, lay: 'flat', normal: NORTH, picked: false,
  own: { lay: 'flat', normal: NORTH, why: 'flat' }, ...p,
})
const view = (...parts: SidePart[]): SidesView => ({ id: 'abc', parts, from: null })

test('a part the box lays flat for you says so, and its sides tag that one', () => {
  assert.deepEqual(partWords(part(), null), { value: 'Laid flat for you', line: 'Its flattest side · Touches 6 cm² · 3 mm tall' })
  const opts = partOptions(part(), null)
  assert.deepEqual(opts.map((o) => [o.title, o.tags, o.on]), [
    ['3 mm tall', ['flattest', 'laid flat for you'], true],
    ['3 mm tall', [], false],
    ['20 mm tall', ['as in the file'], false],
    ['20 mm tall', [], false],
    ['30 mm tall', [], false],
  ])
  assert.equal(opts[4].note, 'Touches 60 mm² · supports under about 1 cm²')
  assert.equal(opts[2].normal, null)
})

test("a side picked is the side you picked; the file's own bottom picked is as in the file", () => {
  assert.equal(partWords(part({ lay: 'side', normal: EAST, down: EAST, picked: true }), null).value, 'The side you picked')
  assert.equal(partWords(part({ lay: 'side', normal: EAST, down: EAST, picked: true }), null).line, 'Touches 60 mm² · 30 mm tall')
  assert.deepEqual(partWords(part({ lay: 'file', normal: null, picked: true }), null), { value: 'As in the file', line: 'Touches 90 mm²' })
})

test("a model that sits fine is as in the file; one gathered from a printer's plate is as that printer printed it", () => {
  const fine = part({ lay: 'file', normal: null, own: { lay: 'file', normal: null, why: 'file' } })
  assert.equal(partWords(fine, null).value, 'As in the file')
  assert.equal(ownTag(fine, null), null)
  const gathered = part({ lay: 'file', normal: null, own: { lay: 'file', normal: null, why: 'plate' } })
  assert.equal(partWords(gathered, 'Workshop').value, 'As Workshop printed it')
  assert.deepEqual(partOptions(gathered, 'Workshop').find((o) => o.normal == null)!.tags, ['as in the file', 'as Workshop printed it'])
})

test('the Lying row: one part in its words, several as a count; nothing to pick when it sits one way', () => {
  assert.deepEqual(sideRow(null), { value: 'Reading it…', line: 'Which side goes down' })
  assert.equal(sideRow(view(part())).value, 'Laid flat for you')
  const two = view(part(), part({ n: 1, name: '1-pin.stl', lay: 'side', normal: EAST, picked: true }))
  assert.deepEqual(sideRow(two), { value: '1 on a side you picked', line: '2 parts, each on its own side' })
  assert.deepEqual(sideRow(view(part(), part({ n: 1 }))), { value: "Each part's own", line: '2 parts, each on its own side' })
  assert.equal(canPickSide(view(part())), true)
  assert.equal(canPickSide(view(part({ lying: null }))), false)
  assert.equal(partName('0-bushing_open.stl'), 'Bushing open')
  assert.equal(partName('Phone stand.stl'), 'Phone stand')
})

test("a tap shows at once: the part's own side is no pick, another is; the box is sent the same", () => {
  const v = view(part())
  const east = withSide(v, 0, EAST).parts[0]
  assert.deepEqual([east.lay, east.normal, east.picked], ['side', EAST, true])
  const file = withSide(v, 0, null).parts[0]
  assert.deepEqual([file.lay, file.normal, file.picked], ['file', null, true])
  const back = withSide(withSide(v, 0, EAST), 0, NORTH).parts[0]
  assert.deepEqual([back.lay, back.normal, back.picked], ['flat', NORTH, false])
  assert.deepEqual(pickOf(0, EAST), { part: 0, lay: 'side', down: EAST })
  assert.deepEqual(pickOf(1, null), { part: 1, lay: 'file' })
})

test('a new side is a new setup; a model without sides read keeps the old key', () => {
  const k = (s = '') => setupKey('desk', 1, 'pla', DEFAULT_HOW, s)
  assert.equal(k(), 'desk|1|pla|everyday|||')
  assert.notEqual(k(sidesKey(view(part()))), k(sidesKey(withSide(view(part()), 0, EAST))))
  assert.equal(sidesKey(view(part({ normal: null }))), 'file')
})

test('the picture: one part turned onto its side; several laid out on the plate once any is turned', () => {
  // one triangle standing up in the y = 0 plane, its outward side facing -y
  const tri = new Float32Array([0, 0, 0, 10, 0, 0, 0, 0, 20])
  const one = laidPicture([tri], view(part({ normal: [0, -1, 0] })))!
  const zs = [one[2], one[5], one[8]]
  assert.ok(Math.max(...zs) < 1e-4, 'laid on the side that faced -y: flat on the plate')
  assert.equal(laidPicture([tri], view(part({ normal: null }))), tri)
  const asDrawn = laidPicture([tri, tri], view(part({ normal: null }), part({ n: 1, normal: null })))!
  assert.equal(asDrawn.length, 18)
  assert.equal(laidPicture([null], view(part())), null)
})

test("the printer's own sides read as before (shared with its Print)", () => {
  const opts = sideOptions(MOUNT, null)
  assert.equal(opts.find((o) => o.on)!.title, '20 mm tall')
  assert.deepEqual(opts[0].tags, ['flattest'])
})
