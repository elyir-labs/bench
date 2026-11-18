// Pins the 7" round (design/bench-7in/, A + A): the chip for another printer, and each tile's one line.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { needChip, ordered, tileLine, type BenchPrinter } from '../src/bench-app/bench.ts'

const job = (name: string, progress: number, eta: string | null) =>
  ({ name, filename: name + '.gcode', thumbnail: null, grams: null, state: 'printing', progress, layer: null, layers: null,
     elapsed_s: 0, total_s: 0, remaining_s: 3600, eta: null, eta_clock: eta, estimated_s: null, colors: [], material: 'pla' })
const intent = (state: string, extra: Record<string, unknown> = {}) =>
  ({ version: 1, state, phase: '', since: '', headline: '', detail: '', safe: true, expires: null, actions: [], steps: [], job: null, spools: [], ...extra }) as any
const P = (name: string, i: any): BenchPrinter => ({ id: name.toLowerCase(), name, live: true, intent: i })

const done = P('Studio', intent('finished', { headline: 'Done.', job: job('Bin lid', 1, null) }))
const printing = P('Workshop', intent('printing', { job: job('Phone stand', 0.4, '8:59 pm') }))
const ready = P('Desk', intent('ready', { detail: '4 spools loaded.' }))
const runout = P('Garage', intent('needs_you', { headline: 'Slot 2 ran out.', job: job('Vent plug', 0.6, null) }))

test('the chip names the other printer that most needs a person', () => {
  const tiles = ordered([done, printing, ready, runout])
  assert.deepEqual(needChip(tiles, 'workshop'), { id: 'garage', label: 'Garage needs you', tone: 'amber' })
  assert.deepEqual(needChip(tiles, 'garage'), { id: 'studio', label: 'Studio needs you', tone: 'amber' })
  assert.equal(needChip(ordered([printing, ready]), 'workshop'), null)
})

test('each tile has one line: when, what is loaded, or what happened', () => {
  const [r, d, p, k] = ordered([done, printing, ready, runout])
  assert.equal(tileLine(p), 'Done at 8:59 pm')
  assert.equal(tileLine(k), '4 spools loaded.')
  assert.equal(tileLine(d), 'Done. Bin lid · PLA')
  assert.equal(tileLine(r), 'Slot 2 ran out. Vent plug · PLA')
})
