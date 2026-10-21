// Pins Move and heat (design/hands-on/, C, picked 18 October 2026): the jobs in the drawn order, the words that
// follow what moves in Z, and what the pad and the Z buttons send. The boards there are the spec.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { PAD, heldChip, jobs, rowLine, sheetLine, whereLine, zButtons, type HandsView } from '../src/intent/hands.ts'

const view = (over: Partial<HandsView> = {}): HandsView => ({
  why_not: null, z_moves: 'head', homed: true, homing: false, position: { x: 175, y: 175, z: 30 },
  limits: { min: [0, 0, -5], max: [350, 350, 340] }, steps: [1, 10, 50], material: 'PETG', clean_temp: 240,
  nozzle_presets: [], bed_presets: [], held: null, heat: [], ...over,
})

test('the jobs: five, then Move it myself last', () => {
  const j = jobs(view())
  assert.deepEqual(j.map((x) => x.title), ['Get at the bed', 'Clean the nozzle', 'Heat the nozzle', 'Heat the bed', 'Let go of the motors', 'Move it myself'])
  assert.deepEqual(j.map((x) => x.action), ['hands_clear', 'hands_clean', 'hands_nozzle', null, 'hands_motors_off', null])
  assert.equal(j[1].line, 'Hot for PETG, at the front')
  assert.equal(j[3].line, 'Warm up for a material')   // what Now's Something else asked (design/hands-on-find/, B)
})

test('with nothing in the head, Clean the nozzle heats for PLA', () => {
  assert.equal(jobs(view({ material: null }))[1].line, 'Hot for PLA, at the front')
})

test('named by the machine: a gantry goes up, a bed goes down', () => {
  assert.equal(jobs(view())[0].line, 'Raises the head out of the way')
  assert.equal(jobs(view({ z_moves: 'bed' }))[0].line, 'Lowers the bed out of the way')
  assert.deepEqual(zButtons('head'), [{ label: 'Head up', arrow: 'up', dir: 1 }, { label: 'Head down', arrow: 'down', dir: -1 }])
  // a bed going up is Z going down
  assert.deepEqual(zButtons('bed'), [{ label: 'Bed up', arrow: 'up', dir: -1 }, { label: 'Bed down', arrow: 'down', dir: 1 }])
})

test('the pad: up on the screen is toward the back', () => {
  assert.deepEqual(PAD.find((p) => p.arrow === 'up'), { arrow: 'up', axis: 'y', dir: 1 })
  assert.deepEqual(PAD.find((p) => p.arrow === 'left'), { arrow: 'left', axis: 'x', dir: -1 })
})

test("Care's row: why not, or at the printer", () => {
  assert.equal(rowLine(view(), false), 'Get at the bed, clean the nozzle, or move it yourself.')
  assert.equal(rowLine(view({ why_not: "Not while it's printing." }), false), "Not while it's printing.")
  assert.equal(rowLine(view(), true), 'At the printer.')
})

test('where the head is, or that the first move finds home', () => {
  assert.equal(whereLine(view()), 'X 175 · Y 175 · Z 30')
  assert.equal(whereLine(view({ position: { x: 175.4, y: 10, z: 50.25 } })), 'X 175 · Y 10 · Z 50.3')
  assert.equal(whereLine(view({ homed: false, position: null })), 'Finds home first')
  assert.equal(whereLine(view({ homed: false, homing: true, position: null })), 'Finding home…')
})

test('the sheet and Now say what is hot', () => {
  assert.equal(sheetLine('Workshop', 23.4, 22), 'Workshop is free. The nozzle is 23°, the bed 22°.')
  assert.equal(heldChip({ kind: 'clean', target: 240, minutes: 15 }, 186.2), 'Nozzle 186° of 240°')
  assert.equal(heldChip({ kind: 'clear', z: 150, minutes: 15 }, 25), 'Z 150')
  assert.equal(heldChip(null, 25), null)
})

test('a printer that only takes heat (a Kobra over LAN mode): the heat jobs, then Set the heat', () => {
  const j = jobs(view({ can_move: false }))
  assert.deepEqual(j.map((x) => x.title), ['Heat the nozzle', 'Heat the bed', 'Set the heat'])
  assert.equal(rowLine(view({ can_move: false }), false), 'Heat the nozzle or the bed.')
})
