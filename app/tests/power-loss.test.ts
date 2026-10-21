// Pins power cuts on Now, picked on 21 October 2026 (design/power-loss/, A): the hold's ring and lines, the countdown
// once the power is back, the lost print's words, and how many of each part Print the rest asks for.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { doneWords, holdFacts, holdRing, restWords } from '../src/intent/lost.ts'
import { copiesByPart } from '../src/slice/skipped.ts'
import type { LostView, OutageView } from '../src/intent/types.ts'

const hold: OutageView = { back: false, held: 'print', minutes: 2, battery: 70, runtime_min: 50, bed: 45, layer: 61, heating: false, to: 215, carry_in: null }
const lost: LostView = { file: 'phone_stand.gcode', name: 'Phone stand', layer: 61, layers: 140, z: 12.2, height: 28, pct: 44,
  material: 'PLA', off_at: '2:14 am', back_at: '5:24 am', held: false, objects: [] }

test('holding: the ring is the battery, and the lines say what stays on and what happens next', () => {
  assert.deepEqual(holdRing(hold, 150), { value: 0.7, text: '70%', label: 'battery' })
  assert.deepEqual(holdFacts(hold), ['Bed kept at 45° so the part stays stuck.', 'Battery: about 50 min like this.',
    'It carries on by itself when the power is back.'])
  assert.equal(holdFacts({ ...hold, held: 'paused', bed: null })[1], 'It stays paused when the power comes back.')
})

test('power back: a countdown while it settles, then the nozzle warming', () => {
  assert.deepEqual(holdRing({ ...hold, back: true, carry_in: 8 }, 150), { value: 1 - 8 / 30, text: '0:08', label: 'to carry on' })
  const warming = holdRing({ ...hold, back: true, heating: true }, 172)
  assert.equal(warming.text, '172°')
  assert.equal(warming.label, 'of 215°')
})

test('a lost print says how far it got and what printing the rest makes', () => {
  assert.equal(doneWords(lost), '44% done · 12.2 of 28 mm')
  assert.equal(doneWords({ ...lost, z: null }), '44% done')
  assert.equal(restWords(lost), 'The bottom 12.2 mm is done. The top 15.8 mm prints as its own part, to glue on.')
})

test('print the rest asks for as many of each part as were still printing', () => {
  const n = copiesByPart(['p0c0__bushing', 'p0c1__bushing', 'p2c0__cover', 'loose_object'])
  assert.deepEqual([...n], [[0, 2], [2, 1]])
})
