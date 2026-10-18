// Pins the Bench Box's home (design/bench-box/, D, agreed 4 October 2026). The boards there are the spec.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { offLine, ordered, sentence, sizeFor, tileOf, type BenchPrinter } from '../src/bench-app/bench.ts'

const job = (name: string, progress: number, eta: string | null, remaining: number | null, material = 'pla') =>
  ({ name, filename: name + '.gcode', thumbnail: `.thumbs/${name}.png`, grams: null, state: 'printing', progress, layer: null, layers: null,
     elapsed_s: 0, total_s: 0, remaining_s: remaining, eta: null, eta_clock: eta, estimated_s: null, colors: [], material })
const intent = (state: string, extra: Record<string, unknown> = {}) =>
  ({ version: 1, state, phase: '', since: '', headline: '', detail: '', safe: true, expires: null, actions: [], steps: [], job: null, spools: [], ...extra }) as any
const P = (name: string, i: any, live = true): BenchPrinter => ({ id: name.toLowerCase(), name, live, intent: i })

const BENCH = [
  P('Desk', intent('ready', { detail: 'White PLA loaded' })),
  P('Workshop', intent('printing', { job: job('Phone stand', 0.42, '4:20 pm', 5600, 'petg') })),
  P('Kobra 3', intent('printing', { job: job('Cable clips', 0.78, '4:45 pm', 2500) })),
  P('Studio', intent('needs_you', { headline: 'Slot 2 ran out at 61%.', job: job('Vent plug', 0.61, null, null),
                                  actions: [{ id: 'load', label: 'Load slot 2', primary: true, style: 'amber' }, { id: 'stop', label: 'Stop', primary: false, style: 'red', hold: true }] })),
  P('Kobra Max', intent('finished', { headline: 'Done. Take it off the bed.', job: job('Bin lid', 1, null, 0),
                                      actions: [{ id: 'print_another', label: 'Print another', primary: true, style: 'green' },
                                                { id: 'taken_off', label: "I've taken it off", primary: false, style: 'default' }] })),
  P('Kobra 3 #2', null, false), P('Monoprice SLA', null, false),
]

test('needs you leads, then printing by when it is done, then ready, then off', () => {
  assert.deepEqual(ordered(BENCH).map((t) => t.name), ['Studio', 'Kobra Max', 'Kobra 3', 'Workshop', 'Desk', 'Kobra 3 #2', 'Monoprice SLA'])
})

test('a tile carries the printer\'s own words and its one next thing, never a hold action', () => {
  const r = tileOf(BENCH[3])
  assert.deepEqual([r.tone, r.word, r.says, r.what, r.action, r.frac], ['amber', 'Needs you', 'Slot 2 ran out at 61%.', 'Vent plug · PLA', 'Load slot 2', 0.61])
  const o = tileOf(BENCH[1])
  assert.deepEqual([o.tone, o.word, o.says, o.what, o.action], ['blue', 'Printing', 'Done at 4:20 pm', 'Phone stand · PETG', null])
  assert.deepEqual([tileOf(BENCH[4]).word, tileOf(BENCH[4]).action], ['Done', "I've taken it off"])   // the bed before another
  assert.equal(tileOf(BENCH[0]).action, 'Print a model')
  assert.equal(tileOf(BENCH[5]).tone, 'off')
})

test('the sentence says who needs you and when the next one is done', () => {
  assert.equal(sentence(ordered(BENCH)), 'Two need you: Studio and Kobra Max. Kobra 3 is done at 4:45 pm.')
  assert.equal(sentence(ordered([BENCH[0], BENCH[1], BENCH[3]])), 'Studio needs you. Workshop is done at 4:20 pm.')
  assert.equal(sentence(ordered([BENCH[0], BENCH[1]])), 'Nothing needs you. Workshop is done at 4:20 pm.')
  assert.equal(sentence(ordered([BENCH[0]])), 'Everything is ready to print.')
  assert.equal(sentence(ordered([BENCH[5]])), 'No printer is on.')
  assert.equal(sentence([]), 'No printers yet.')
})

test('the tiles get smaller as the bench grows; the ones that are off fold into one line', () => {
  assert.deepEqual([1, 4, 5, 9, 10, 20].map(sizeFor), ['big', 'big', 'compact', 'compact', 'rows', 'rows'])
  assert.equal(offLine(ordered(BENCH)), '2 off · Kobra 3 #2 · Monoprice SLA')
  assert.equal(offLine(ordered([BENCH[0]])), null)
})
