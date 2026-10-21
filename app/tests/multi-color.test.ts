// Pins the Colors card (design/multi-color/, B, picked 21 October 2026): how a 3MF's colors find loaded spools,
// what the card says about the changes and the swaps by hand, and the plate drawn in its colors.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { colorWord, costLine, footColors, matchFileColors, minutesWords, spoolLine, tooMany, tooManyWords, unsorted,
  type ColorsResult, type PlateSpool } from '../src/slice/colors.ts'
import { plateRuns } from '../src/slice/plate.ts'

const WHITE = '#F2F2F0', BLACK = '#2B2B2B', GOLD = '#C9A227', BLUE = '#2F7BEA'
const loaded = (slot: number, color: string, material = 'PLA', status = 'ready', in_use = false) =>
  ({ slot, color, material, status: status as 'ready', in_use, name: `${colorWord(color)} ${material}` })
const SPOOLS = [loaded(0, '#D94B45'), loaded(1, '#F4F4F2'), loaded(2, '#1C1C1E', 'PLA', 'low'), loaded(3, '#2563EB'),
  loaded(4, '#F5C542', 'PETG'), loaded(5, '#F4F4F2'), { slot: 6, color: null, material: null, status: 'empty' as const, in_use: false }]
const change = (at: number, to: number, hand = false, purge = 50) => ({ layer: 1, at, to, hand, purge })
const result = (changes: ReturnType<typeof change>[], spools = 2): ColorsResult => ({
  spools: Array.from({ length: spools }, (_, k) => ({ spool: k, parts: [k], first: k === 0,
    swaps: changes.filter(c => c.to === k && c.hand).map(c => c.at), changes: changes.filter(c => c.to === k).length })),
  changes, hand_swaps: changes.filter(c => c.hand).length, unit_changes: changes.filter(c => !c.hand).length,
  changes_seconds: changes.length * 105, grams: [2, 1],
})

test("a 3MF's colors take the loaded spools that match, each once; one that nothing matches waits", () => {
  const file = [WHITE, BLACK, GOLD, BLUE].map(color => ({ color, material: 'PLA', used: true }))
  const got = matchFileColors(file, SPOOLS, ['PLA', 'PETG'])
  assert.deepEqual(got.map(s => s.slot), [1, 2, null, 3])
  assert.equal(got[2].name, 'Yellow PLA')                // the yellow PETG is near, but another material
  assert.ok(unsorted(got[2], true) && !unsorted(got[2], false))
  // two whites in the file: the second white spool, not the same one twice
  const twice = matchFileColors([WHITE, WHITE].map(color => ({ color, material: 'PLA', used: true })), SPOOLS, ['PLA'])
  assert.deepEqual(twice.map(s => s.slot), [1, 5])
  // a color the file has but doesn't use takes no spool
  assert.equal(matchFileColors([{ color: WHITE, material: 'PLA', used: false }], SPOOLS, ['PLA'])[0].slot, null)
})

test('times read the way people say them', () => {
  assert.equal(minutesWords([180]), '3 min')
  assert.equal(minutesWords([180, 480, 1620]), '3, 8 and 27 min')
  assert.equal(minutesWords([60, 420, 660, 960, 1200, 1500]), 'from 1 to 25 min')
})

test('the card says who changes the color and when', () => {
  const unitOnly = result([change(180, 1)])
  assert.deepEqual(costLine(unitOnly, 'chute', true), { strong: '1 change, about 3 min in, adds 2 min.', rest: 'The old color goes out of the chute: 0.1 g.' })
  const mixed = result([change(180, 1), change(1680, 2, true), change(1900, 0)], 3)
  assert.equal(costLine(mixed, 'tower', true).strong, 'The unit does 2 changes; you swap once, at about 28 min.')
  assert.equal(footColors(mixed, 3), "You're needed once, at about 28 min")
  const desk = result([change(180, 1, true), change(480, 2, true), change(1620, 3, true)], 4)
  assert.equal(costLine(desk, 'swap', false).strong, 'You swap 3 times, at about 3, 8 and 27 min.')
})

test('too many swaps by hand: counted in printing time, not the swaps themselves', () => {
  // 62 swaps, 20 s of printing apart; each change takes 105 s, which `at` counts in
  const changes = Array.from({ length: 62 }, (_, i) => change(300 + i * 20 + i * 105, i % 2 ? 0 : 1, true))
  const t = tooMany(result(changes))!
  assert.deepEqual([t.count, t.every], [62, 20])
  assert.equal(tooManyWords(t), 'about one every 20 seconds for the first 20 minutes')
  assert.equal(tooMany(result(changes.slice(0, 10))), null)
})

test("a color's line: its slot, by hand, or not loaded yet", () => {
  const s = (slot: number | null, hand = false): PlateSpool => ({ slot, material: 'PLA', color: GOLD, name: 'Gold PLA', hand })
  const r = result([change(1680, 1, true)])
  assert.deepEqual(spoolLine(s(3), 0, r, true, 'Gnome'), { text: 'Slot 4 · Gnome', amber: false })
  assert.deepEqual(spoolLine(s(null, true), 1, r, true, ''), { text: 'The print waits for you at about 28 min', amber: false })
  assert.equal(spoolLine(s(null), 1, r, true, 'The hat').amber, true)
  // no unit, and the slice starts with the second color (parts one after the other): load it first
  const later = { ...r, spools: [{ ...r.spools[0], first: false }, { ...r.spools[1], first: true }] }
  assert.deepEqual(spoolLine(s(null, true), 1, later, false, 'Idler'), { text: 'Idler · it prints first: load it before you start', amber: true })
})

test('the plate is drawn in its colors, copy by copy', () => {
  const t = (n: number) => new Float32Array(n * 9)
  const parts = [{ tris: t(4), copies: 2, scale: 1, runs: [{ count: 4, color: WHITE }] },
                 { tris: t(3), copies: 1, scale: 1, runs: [{ count: 2, color: BLUE }, { count: 1, color: GOLD }] }]
  const placed = [{ part: 0, x: 0, y: 0, turn: 0 }, { part: 1, x: 50, y: 0, turn: 0 }, { part: 0, x: 90, y: 0, turn: 0 }]
  assert.deepEqual(plateRuns(parts, placed), [{ end: 4, color: WHITE }, { end: 6, color: BLUE }, { end: 7, color: GOLD }, { end: 11, color: WHITE }])
})
