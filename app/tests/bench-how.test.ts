// Pins how a model on the Bench Box's shelf prints (design/bench-how/, A; docs/bench-how.md): the tiles' words from a
// how, a change laid over it as the box does, and the setup key that says when Print on can reuse a setup.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { aboutLine, changedWords, costWords, DEFAULT_HOW, howOf, howTiles, mergeHow, minutes, purposeList, settingRows, settingValue, setupKey, supportsTile, type How } from '../src/bench-app/how.ts'
import type { Editable } from '../src/slice/plan.ts'

const EDITABLE: Editable[] = [
  { key: 'layer_height', label: 'Layer height', kind: 'number', min: 0.08, max: 0.32, step: 0.04, unit: 'mm', default: '0.2', help: '' },
  { key: 'wall_loops', label: 'Walls', kind: 'number', min: 1, max: 10, step: 1, default: '2', help: '' },
  { key: 'sparse_infill_pattern', label: 'Inside', kind: 'choice', default: 'crosshatch', choices: [['crosshatch', 'Crosshatch'], ['gyroid', 'Gyroid']], help: '' },
]
const PURPOSES = [{ id: 'everyday', label: 'Everyday', summary: 'Good all round. The one to pick when unsure.' },
                  { id: 'draft', label: 'Quick draft', summary: 'Fast and light. Checking a fit, or a first try.' }]
const how = (h: Partial<How> = {}): How => ({ ...DEFAULT_HOW, settings: {}, ...h })

test("a model with no how yet: Everyday, the printer's usual supports, each part's own brim, nothing changed", () => {
  assert.deepEqual(howOf({}), DEFAULT_HOW)
  assert.deepEqual(howOf({ how: { purpose: 'strong' } as Partial<How> }), { purpose: 'strong', supports: null, brim: null, settings: {} })
  const tiles = howTiles(howOf(null), { purposes: PURPOSES, editable: EDITABLE, usual: 'normal', printer: 'Desk' })
  assert.deepEqual(tiles.map((t) => [t.label, t.value, t.line]), [
    ["It's for", 'Everyday', 'Good all round'],
    ['Supports', 'Normal', "Comes off in blocks · Desk's usual"],
    ['Brim', "Each part's own", 'As it last printed'],
    ['Changed', 'Nothing', 'Every setting'],
  ])
  assert.equal(tiles[3].link, true)
})

test("the tiles say what's kept with the model", () => {
  const tiles = howTiles(how({ purpose: 'draft', supports: 'tree', brim: 'ears', settings: { wall_loops: '4' } }),
    { purposes: PURPOSES, editable: EDITABLE, usual: 'normal', printer: 'Desk' })
  assert.deepEqual(tiles.map((t) => [t.value, t.line]), [
    ['Quick draft', 'Fast and light'],
    ['Tree', 'Branches'],
    ['Corners only', 'Pads that snap off'],
    ['Walls 4', 'Every setting'],
  ])
  assert.deepEqual(howTiles(how({ brim: 'all' }), {}).map((t) => t.value)[2], 'All round')
  assert.deepEqual(howTiles(how({ brim: 'auto' }), {}).map((t) => t.value)[2], "Orca's own")
  assert.deepEqual(howTiles(how({ purpose: 'display' }), {})[0].value, 'Looks best')     // before the slicer's options come
})

test("supports left to the printer: its usual, or said plainly when there's none to ask", () => {
  assert.deepEqual(supportsTile(how(), 'tree', 'Workshop'), { value: 'Tree', line: "Branches · Workshop's usual" })
  assert.deepEqual(supportsTile(how(), null, 'Workshop'), { value: 'Usual', line: "Workshop's usual" })
  assert.deepEqual(supportsTile(how(), null, null), { value: 'Usual', line: "The printer's usual" })
  assert.deepEqual(supportsTile(how({ supports: 'off' }), 'tree', 'Workshop'), { value: 'Off', line: 'Overhangs print in the air' })
})

test('Changed: nothing, the one setting, or how many', () => {
  assert.equal(changedWords(how(), EDITABLE), 'Nothing')
  assert.equal(changedWords(how({ settings: { layer_height: '0.16' } }), EDITABLE), 'Layer height 0.16 mm')
  assert.equal(changedWords(how({ settings: { sparse_infill_pattern: 'gyroid' } }), EDITABLE), 'Inside Gyroid')
  assert.equal(changedWords(how({ settings: { wall_loops: '4', layer_height: '0.12', sparse_infill_pattern: 'gyroid' } }), EDITABLE), '3 settings')
  assert.equal(changedWords(how({ settings: { brim_width: '3' } }), EDITABLE), '1 setting')   // not on the slicer's list
})

test("a change laid over a how as the box does: fields replace, settings merge, null removes", () => {
  const h = how({ supports: 'tree', settings: { wall_loops: '4', layer_height: '0.16' } })
  assert.deepEqual(mergeHow(h, { purpose: 'strong' }), { ...h, purpose: 'strong' })
  assert.deepEqual(mergeHow(h, { supports: null }).supports, null)                    // back to the printer's usual
  assert.deepEqual(mergeHow(h, { brim: 'none' }).brim, 'none')
  assert.deepEqual(mergeHow(h, { settings: { wall_loops: null, sparse_infill_pattern: 'gyroid' } }).settings,
    { layer_height: '0.16', sparse_infill_pattern: 'gyroid' })
  assert.deepEqual(h.settings, { wall_loops: '4', layer_height: '0.16' })              // never changed in place
})

test('the setup key: the same setup while nothing changed, a new one when how does', () => {
  const a = setupKey('desk', 1, 'PLA#fff', how({ settings: { wall_loops: '4', layer_height: '0.16' } }))
  assert.equal(a, setupKey('desk', 1, 'PLA#fff', how({ settings: { layer_height: '0.16', wall_loops: '4' } })))   // order doesn't matter
  for (const other of [setupKey('workshop', 1, 'PLA#fff', how({ settings: { wall_loops: '4', layer_height: '0.16' } })),
                       setupKey('desk', 2, 'PLA#fff', how({ settings: { wall_loops: '4', layer_height: '0.16' } })),
                       setupKey('desk', 1, 'PLA#fff', how({ settings: { wall_loops: '5', layer_height: '0.16' } })),
                       setupKey('desk', 1, 'PLA#fff', how({ supports: 'off', settings: { wall_loops: '4', layer_height: '0.16' } })),
                       setupKey('desk', 1, 'PLA#fff', how({ purpose: 'draft', settings: { wall_loops: '4', layer_height: '0.16' } }))]) {
    assert.notEqual(a, other)
  }
})

test('the line under the buttons, and a purpose\'s price', () => {
  assert.equal(aboutLine(72 * 60, 21.4, 'Desk'), 'About 1 h 12 min · 21 g on Desk')
  assert.equal(aboutLine(null, null, 'Desk'), '')
  assert.equal(costWords(48 * 60, 17), '48 min · 17 g')
  assert.equal(minutes(120 * 60), '2 h')
  assert.equal(minutes(20), 'under a minute')
})

test('Every setting: the model\'s own, then the rest as the printer prints them', () => {
  const h = how({ settings: { wall_loops: '4' } })
  const rows = settingRows(EDITABLE, h, { layer_height: '0.2', wall_loops: '2', sparse_infill_pattern: 'gyroid' }, 'Desk')
  assert.deepEqual(rows.map((r) => [r.label, r.now, r.mine, r.why]), [
    ['Layer height', '0.2 mm', false, "Desk's own"],
    ['Walls', '4', true, "This model's own"],
    ['Inside', 'Gyroid', false, "Desk's own"],
  ])
  assert.equal(settingRows(EDITABLE, h, null, null)[0].why, "The printer's own")
  assert.equal(settingRows(EDITABLE, h, null, null)[0].now, '0.2 mm')                 // Orca's own before it's set up
  assert.equal(settingValue(EDITABLE[1], h, { wall_loops: '2' }), '4')
  assert.equal(settingValue(EDITABLE[0], h, { layer_height: '0.16' }), '0.16')
  assert.equal(settingValue(EDITABLE[0], h, null), '0.2')
})

test('the four purposes in the slicer\'s order, with its words', () => {
  assert.deepEqual(purposeList(PURPOSES).map((p) => p.label), ['Quick draft', 'Everyday', 'Looks best', 'Strong'])
})
