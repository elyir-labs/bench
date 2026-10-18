// Pins the Bench Box's tabs (design/bench-box/, D): Print (whichever is free), Spools and Care, each gathered
// from what every printer says about itself.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { byMaterial, careRows, careSentence, spoolCards, spoolSentence, whicheverIsFree } from '../src/bench-app/tabs.ts'
import type { BenchPrinter } from '../src/bench-app/bench.ts'

const job = (name: string, eta: string | null, remaining: number | null) =>
  ({ name, filename: name + '.gcode', thumbnail: null, grams: null, state: 'printing', progress: 0.4, layer: null, layers: null,
     elapsed_s: 0, total_s: 0, remaining_s: remaining, eta: null, eta_clock: eta, estimated_s: null, colors: [], material: 'pla' })
const intent = (state: string, extra: Record<string, unknown> = {}) =>
  ({ version: 1, state, phase: '', since: '', headline: '', detail: '', safe: true, expires: null, actions: [], steps: [], job: null, spools: [], ...extra }) as any
const P = (name: string, i: any, live = true): BenchPrinter => ({ id: name.toLowerCase(), name, live, intent: i })
const spool = (slot: number, material: string | null, status = 'ready', extra: Record<string, unknown> = {}) =>
  ({ slot, color: '#F4F4F2', material, grams: 800, status, in_use: false, rfid: false, name: material ? `White ${material}` : null, ...extra })
const care = (name: string, progress: number, due = false, snoozed = false) =>
  ({ id: name, name, note: '', due, snoozed, progress, label: `${Math.round(progress * 40)} of 40 print hours` })

const BENCH = [
  P('Desk', intent('ready', { detail: 'White PLA loaded. Time to wipe the bed.', spools: [spool(1, 'PLA', 'ready', { in_use: true })],
                              care: { items: [care('Wipe the bed', 0.8)], due: 0, hint: null } })),
  P('Workshop', intent('printing', { job: job('Phone stand', '4:20 pm', 5600),
                                 spools: [spool(1, 'PETG', 'ready', { in_use: true }), spool(2, 'PLA', 'low', { grams: 120 }), spool(3, null, 'empty'), spool(4, 'PLA', 'low', { grams: 90 }), spool(5, 'PLA', 'low', { grams: 60 }), spool(6, 'PLA', 'low', { grams: 30 })],
                                 care: { items: [care('Clean the nozzle', 1, true), care('Check the belts', 0.3)], due: 1, hint: null } })),
  P('Kobra 3', intent('printing', { job: job('Cable clips', '4:45 pm', 2500) })),
  P('Kobra Max', intent('finished', { headline: 'Done. Take it off the bed.' })),
  P('Studio', intent('needs_you', { headline: 'Slot 2 ran out at 61%.', spools: [spool(1, 'ASA')] })),
  P('Kobra 3 #2', null, false),
]

test('Print: the soonest free first, and why each is where it is', () => {
  const rows = whicheverIsFree(BENCH)
  assert.deepEqual(rows.map((r) => r.name), ['Desk', 'Kobra Max', 'Kobra 3', 'Workshop', 'Studio'])   // the off one isn't offered
  assert.deepEqual(rows.map((r) => r.line), ['Free now · White PLA loaded.', 'Free once the bed is cleared',
    'After the cable clips, about 4:45 pm', 'After the phone stand, about 4:20 pm', 'Stopped: Slot 2 ran out at 61%.'])
  assert.deepEqual(rows.map((r) => [r.free, r.stopped]), [[true, false], [false, false], [false, false], [false, false], [false, true]])
})

test('Spools: every printer\'s, the ones running short first, in each printer\'s own words', () => {
  const cards = spoolCards(BENCH)
  assert.deepEqual(cards.map((c) => c.name), ['Workshop', 'Desk', 'Studio'])   // Kobras report none; the off one isn't there
  assert.deepEqual(cards[0].spools.map((s) => [s.name, s.meta, s.tone]),
    [['White PETG', 'in use', 'accent'], ['White PLA', '120 g, low', 'amber'], ['Empty', '', null], ['White PLA', '90 g, low', 'amber'],
     ['White PLA', '60 g, low', 'amber'], ['White PLA', '30 g, low', 'amber']])   // an empty slot in a unit is just room
  assert.equal(spoolSentence(cards), 'Four spools need you, on Workshop.')
  const fewer = P('Workshop', intent('ready', { spools: [spool(1, 'PLA', 'low'), spool(2, 'PLA', 'low', { grams: 50 }), spool(3, null, 'empty')] }))
  assert.equal(spoolSentence(spoolCards([fewer])), "Two spools need you: Workshop's slot 1 and Workshop's slot 2.")
  const one = P('Desk', intent('ready', { spools: [spool(0, null, 'empty')] }))
  assert.equal(spoolSentence(spoolCards([one])), 'Desk is empty.')   // a printer's one spool, empty, is short
  assert.equal(spoolSentence(spoolCards([BENCH[0], BENCH[4]])), 'Every spool is loaded: 2 on two printers.')
  assert.equal(spoolSentence([]), 'No printer has said what it has loaded.')
  assert.deepEqual(byMaterial(BENCH), [['PLA', ['Desk', 'Workshop']], ['ASA', ['Studio']], ['PETG', ['Workshop']]])
})

test('Care: what\'s due first, then the nearest, with the printer it belongs to', () => {
  const rows = careRows(BENCH)
  assert.deepEqual(rows.map((r) => `${r.printer}: ${r.name}`), ['Workshop: Clean the nozzle', 'Desk: Wipe the bed', 'Workshop: Check the belts'])
  assert.equal(careSentence(rows), 'Time to clean the nozzle on Workshop.')
  assert.equal(careSentence(careRows([BENCH[0]])), 'Nothing is due. Next: wipe the bed on Desk, 32 of 40 print hours.')
  const two = [BENCH[1], P('Studio', intent('ready', { care: { items: [care('Wipe the bed', 1, true)], due: 1, hint: null } }))]
  assert.equal(careSentence(careRows(two)), `Two things are due, on ${['Workshop', 'Studio'].sort().join(' and ')}.`)   // by name, whatever the names are
  assert.equal(careSentence([]), 'No printer counts its care yet.')
})
