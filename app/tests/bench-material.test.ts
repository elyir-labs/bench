// Pins your filaments on the Bench Box (design/bench-material/, B): In is your list, by name, with where each is loaded;
// what's loaded that isn't one of yours still shows; a printer that asks what's loaded asks for one of yours.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { choices, filamentTitle, printOn, yourFilaments, type MyFilament } from '../src/bench-app/shelf.ts'
import type { BenchPrinter } from '../src/bench-app/bench.ts'

const GRAY = '#8A8D91', WHITE = '#F4F4F2', CHARCOAL = '#3B3B3B'
const spool = (slot: number, material: string, color: string, extra: Record<string, unknown> = {}) =>
  ({ slot, material, color, grams: 800, status: 'ready', in_use: false, rfid: false, ...extra })
const intent = (state: string, spools: unknown[]) =>
  ({ version: 1, state, phase: '', since: '', headline: '', detail: '', safe: true, expires: null, actions: [], steps: [], job: null, spools }) as any
const P = (name: string, i: any): BenchPrinter => ({ id: name.toLowerCase().replace(/ /g, ''), name, live: true, intent: i })

const BENCH = [
  P('Workshop', intent('ready', [spool(0, 'PETG', '#2E9E4F'), spool(2, 'PETG', GRAY), spool(3, 'ABS', WHITE)])),
  P('Kobra 3 #2', intent('ready', [spool(0, 'PETG', GRAY, { direct: true })])),
  P('Kobra 3 Max', intent('ready', [spool(0, 'PLA', '#888888', { direct: true, status: 'unknown', material: null })])),
]
const MINE: MyFilament[] = [
  { id: 'a', preset: 'Anycubic PETG basic', name: 'Anycubic PETG Basic', brand: 'Anycubic', material: 'PETG', color: GRAY },
  { id: 'b', preset: 'PolyTerra PLA @System', name: 'PolyTerra PLA', brand: 'Polymaker', material: 'PLA', color: CHARCOAL },
  { id: 'c', preset: 'PolyLite ABS @System', name: 'PolyLite ABS', brand: 'Polymaker', material: 'ABS', color: WHITE },
]
const PRINTABLE = Object.fromEntries(['workshop', 'kobra3#2', 'kobra3max'].map((id) => [id, { materials: ['PLA', 'PETG', 'ABS'] }]))

test('a filament is called by its brand and name, once', () => {
  assert.equal(filamentTitle({ name: 'PolyTerra PLA', brand: 'Polymaker' }), 'Polymaker PolyTerra PLA')
  assert.equal(filamentTitle({ name: 'Generic PLA', brand: 'Generic' }), 'Generic PLA')
  assert.equal(filamentTitle({ name: 'Anycubic PETG Basic', brand: 'Anycubic' }), 'Anycubic PETG Basic')
})

test('yours, with where each is loaded, loaded first', () => {
  assert.deepEqual(yourFilaments(BENCH, MINE).map((f) => [f.name, f.sub, f.preset]), [
    ['Anycubic PETG Basic', 'Gray · Workshop slot 3, Kobra 3 #2', 'Anycubic PETG basic'],
    ['Polymaker PolyLite ABS', 'White · Workshop slot 4', 'PolyLite ABS @System'],
    ['Polymaker PolyTerra PLA', 'Black · not loaded', 'PolyTerra PLA @System'],
  ])
})

test("In lists yours, then what's loaded that isn't yours; no Any PLA once you have some", () => {
  const ch = choices(BENCH, PRINTABLE, MINE)
  assert.deepEqual(ch.map((f) => f.name), ['Anycubic PETG Basic', 'Polymaker PolyLite ABS', 'Polymaker PolyTerra PLA', 'Green PETG'])
  assert.equal(ch[3].sub, "Workshop · not one of yours yet")
  assert.ok(choices(BENCH, PRINTABLE, []).some((f) => f.name.startsWith('Any ')))
})

test('a printer that asks what is loaded can print one of yours it has no spool for', () => {
  const terra = choices(BENCH, PRINTABLE, MINE).find((f) => f.mine === 'b')!
  const max = printOn(BENCH, terra, PRINTABLE).find((r) => r.name === 'Kobra 3 Max')!
  assert.ok(max.fits && max.asks)
})
